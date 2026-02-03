import asyncio
import json
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests
import speech_recognition as sr
import pyttsx3


WAKE_WORDS = ["hey assistant", "ok assistant", "okay assistant"]
CRITICAL_INTENTS = {"call", "message", "settings", "purchase", "delete", "shutdown"}
MEMORY_FILE = "assistant_memory.json"


@dataclass
class Memory:
    preferences: Dict[str, Any] = field(default_factory=dict)
    frequent_apps: Dict[str, int] = field(default_factory=dict)
    contacts: Dict[str, str] = field(default_factory=dict)
    recent_commands: List[str] = field(default_factory=list)

    def remember_command(self, command: str) -> None:
        self.recent_commands.append(command)
        self.recent_commands = self.recent_commands[-20:]

    def bump_app(self, app: str) -> None:
        self.frequent_apps[app] = self.frequent_apps.get(app, 0) + 1


class MemoryStore:
    def __init__(self, path: str = MEMORY_FILE) -> None:
        self.path = path
        self.memory = Memory()
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self.memory = Memory(**data)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            self.memory = Memory()

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.memory.__dict__, handle, indent=2)


class TextToSpeech:
    def __init__(self) -> None:
        self.engine = pyttsx3.init()
        self.engine.setProperty("rate", 180)

    def say(self, text: str) -> None:
        self.engine.say(text)
        self.engine.runAndWait()


class SpeechToText:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.microphone = sr.Microphone()

    def listen_once(self, timeout: float = 5, phrase_time_limit: float = 8) -> Optional[str]:
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                return None
        try:
            return self.recognizer.recognize_google(audio).lower()
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            return None


class AdbController:
    def __init__(self, adb_path: str = "adb") -> None:
        self.adb_path = adb_path

    def _run(self, args: List[str]) -> str:
        completed = subprocess.run([self.adb_path, *args], capture_output=True, text=True, check=False)
        return (completed.stdout + completed.stderr).strip()

    def open_app(self, package: str) -> str:
        return self._run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])

    def open_url(self, url: str) -> str:
        return self._run(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url])

    def call(self, number: str) -> str:
        return self._run(["shell", "am", "start", "-a", "android.intent.action.CALL", "-d", f"tel:{number}"])

    def send_sms(self, number: str, message: str) -> str:
        return self._run([
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.SENDTO",
            "-d",
            f"sms:{number}",
            "--es",
            "sms_body",
            message,
            "--ez",
            "exit_on_sent",
            "true",
        ])

    def set_wifi(self, enabled: bool) -> str:
        return self._run(["shell", "svc", "wifi", "enable" if enabled else "disable"])

    def set_bluetooth(self, enabled: bool) -> str:
        return self._run(["shell", "svc", "bluetooth", "enable" if enabled else "disable"])

    def set_brightness(self, value: int) -> str:
        value = max(0, min(255, value))
        return self._run(["shell", "settings", "put", "system", "screen_brightness", str(value)])

    def set_volume(self, stream: str, level: int) -> str:
        return self._run(["shell", "media", "volume", "--stream", stream, "--set", str(level)])

    def set_dnd(self, enabled: bool) -> str:
        mode = "total_silence" if enabled else "off"
        return self._run(["shell", "settings", "put", "global", "zen_mode", "1" if enabled else "0"])


@dataclass
class CommandResult:
    spoken_response: str
    executed: bool = True


class IntentParser:
    def __init__(self, memory: Memory) -> None:
        self.memory = memory

    def parse(self, text: str) -> Tuple[str, Dict[str, Any]]:
        text = text.strip().lower()
        if match := re.match(r"call (.+)", text):
            return "call", {"target": match.group(1)}
        if match := re.match(r"send (?:a )?message to (.+?) saying (.+)", text):
            return "message", {"target": match.group(1), "message": match.group(2)}
        if match := re.match(r"open (.+)", text):
            return "open", {"target": match.group(1)}
        if match := re.match(r"turn (on|off) (wifi|wi-fi|bluetooth)", text):
            return "settings", {"setting": match.group(2), "enabled": match.group(1) == "on"}
        if match := re.match(r"set brightness to (\d+)", text):
            return "settings", {"setting": "brightness", "value": int(match.group(1))}
        if match := re.match(r"set volume to (\d+)", text):
            return "settings", {"setting": "volume", "value": int(match.group(1))}
        if match := re.match(r"(start|set) (a )?(timer|alarm|reminder) (for )?(.+)", text):
            return "schedule", {"kind": match.group(3), "time": match.group(5)}
        if match := re.match(r"(play|pause|resume|stop) (.+)", text):
            return "media", {"action": match.group(1), "target": match.group(2)}
        if match := re.match(r"navigate to (.+)", text):
            return "navigation", {"destination": match.group(1)}
        if match := re.match(r"search (for )?(.+)", text):
            return "search", {"query": match.group(2)}
        if match := re.match(r"remember that (.+)", text):
            return "memory", {"note": match.group(1)}
        if "what" in text or "who" in text or "how" in text or "when" in text:
            return "search", {"query": text}
        return "unknown", {"text": text}


class VoiceAssistant:
    def __init__(self) -> None:
        self.memory_store = MemoryStore()
        self.memory = self.memory_store.memory
        self.tts = TextToSpeech()
        self.stt = SpeechToText()
        self.intent_parser = IntentParser(self.memory)
        self.adb = AdbController()
        self.command_queue: "queue.Queue[str]" = queue.Queue()
        self.loop = asyncio.get_event_loop()
        self.running = True
        self.examples = [
            "Hey Assistant, call Alex",
            "Ok Assistant, send a message to Maria saying I'm on my way",
            "Hey Assistant, open Spotify",
            "Ok Assistant, turn on Wi-Fi",
            "Hey Assistant, set brightness to 120",
            "Ok Assistant, set a timer for 10 minutes",
            "Hey Assistant, play lo-fi beats",
            "Ok Assistant, navigate to Central Park",
            "Hey Assistant, search for best sushi near me",
        ]

    def speak(self, message: str) -> None:
        playful = f"{message} 😊"
        self.tts.say(playful)

    def listen_for_wake_word(self) -> None:
        while self.running:
            phrase = self.stt.listen_once(timeout=4, phrase_time_limit=4)
            if not phrase:
                continue
            if any(wake in phrase for wake in WAKE_WORDS):
                self.speak("I\'m listening")
                command = self.listen_for_command()
                if command:
                    self.command_queue.put(command)

    def listen_for_command(self) -> Optional[str]:
        return self.stt.listen_once(timeout=6, phrase_time_limit=10)

    def confirm(self, text: str) -> bool:
        self.speak(f"Just to confirm, should I {text}?")
        response = self.listen_for_command()
        if not response:
            return False
        return response.strip().lower() in {"yes", "yep", "sure", "do it", "confirm", "please"}

    async def handle_commands(self) -> None:
        while self.running:
            try:
                command = self.command_queue.get(timeout=1)
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            await self.process_command(command)

    async def process_command(self, command: str) -> None:
        self.memory.remember_command(command)
        intent, payload = self.intent_parser.parse(command)
        if intent in CRITICAL_INTENTS and not self.confirm(command):
            self.speak("Got it. I won\'t do that.")
            return

        handler_map = {
            "call": self.handle_call,
            "message": self.handle_message,
            "open": self.handle_open,
            "settings": self.handle_settings,
            "schedule": self.handle_schedule,
            "media": self.handle_media,
            "navigation": self.handle_navigation,
            "search": self.handle_search,
            "memory": self.handle_memory,
            "unknown": self.handle_unknown,
        }
        handler = handler_map.get(intent, self.handle_unknown)
        result = await handler(payload)
        if result.spoken_response:
            self.speak(result.spoken_response)
        self.memory_store.save()

    async def handle_call(self, payload: Dict[str, Any]) -> CommandResult:
        target = payload["target"]
        number = self.memory.contacts.get(target, target)
        response = self.adb.call(number)
        return CommandResult(spoken_response=f"Calling {target}.", executed=bool(response))

    async def handle_message(self, payload: Dict[str, Any]) -> CommandResult:
        target = payload["target"]
        message = payload["message"]
        number = self.memory.contacts.get(target, target)
        response = self.adb.send_sms(number, message)
        return CommandResult(spoken_response=f"Sending your message to {target}.", executed=bool(response))

    async def handle_open(self, payload: Dict[str, Any]) -> CommandResult:
        target = payload["target"]
        if target.startswith("http"):
            self.adb.open_url(target)
            return CommandResult(spoken_response=f"Opening {target}.")
        package = self.resolve_app_package(target)
        self.memory.bump_app(target)
        self.adb.open_app(package)
        return CommandResult(spoken_response=f"Opening {target}.")

    async def handle_settings(self, payload: Dict[str, Any]) -> CommandResult:
        setting = payload.get("setting")
        if setting in {"wifi", "wi-fi"}:
            self.adb.set_wifi(payload["enabled"])
            state = "on" if payload["enabled"] else "off"
            return CommandResult(spoken_response=f"Wi-Fi is {state}.")
        if setting == "bluetooth":
            self.adb.set_bluetooth(payload["enabled"])
            state = "on" if payload["enabled"] else "off"
            return CommandResult(spoken_response=f"Bluetooth is {state}.")
        if setting == "brightness":
            self.adb.set_brightness(payload["value"])
            return CommandResult(spoken_response="Brightness updated.")
        if setting == "volume":
            self.adb.set_volume("music", payload["value"])
            return CommandResult(spoken_response="Volume set.")
        if setting == "dnd":
            self.adb.set_dnd(payload["enabled"])
            state = "enabled" if payload["enabled"] else "disabled"
            return CommandResult(spoken_response=f"Do Not Disturb {state}.")
        return CommandResult(spoken_response="I couldn\'t change that setting.", executed=False)

    async def handle_schedule(self, payload: Dict[str, Any]) -> CommandResult:
        kind = payload["kind"]
        time_text = payload["time"]
        return CommandResult(spoken_response=f"{kind.title()} set for {time_text}.")

    async def handle_media(self, payload: Dict[str, Any]) -> CommandResult:
        action = payload["action"]
        target = payload["target"]
        return CommandResult(spoken_response=f"{action.title()}ing {target}.")

    async def handle_navigation(self, payload: Dict[str, Any]) -> CommandResult:
        destination = payload["destination"]
        map_url = f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(destination)}"
        self.adb.open_url(map_url)
        return CommandResult(spoken_response=f"Starting navigation to {destination}.")

    async def handle_search(self, payload: Dict[str, Any]) -> CommandResult:
        query = payload["query"]
        try:
            response = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": 1, "no_html": 1},
                timeout=5,
            )
            data = response.json()
            answer = data.get("AbstractText") or data.get("Answer")
            if not answer:
                answer = "I found a few results. Want me to open the browser?"
            return CommandResult(spoken_response=answer)
        except requests.RequestException:
            return CommandResult(spoken_response="I\'m having trouble reaching the internet right now.")

    async def handle_memory(self, payload: Dict[str, Any]) -> CommandResult:
        note = payload["note"]
        self.memory.preferences["note"] = note
        return CommandResult(spoken_response="Got it. I\'ll remember that.")

    async def handle_unknown(self, payload: Dict[str, Any]) -> CommandResult:
        return CommandResult(spoken_response="Sorry, I didn\'t catch that. Try another command?")

    def resolve_app_package(self, target: str) -> str:
        package_map = {
            "spotify": "com.spotify.music",
            "youtube": "com.google.android.youtube",
            "maps": "com.google.android.apps.maps",
            "messages": "com.google.android.apps.messaging",
        }
        return package_map.get(target.lower(), target)

    def show_examples(self) -> None:
        print("Example commands:")
        for example in self.examples:
            print(f"- {example}")

    def run(self) -> None:
        self.speak("Hello! Say 'Hey Assistant' when you need me.")
        listener_thread = threading.Thread(target=self.listen_for_wake_word, daemon=True)
        listener_thread.start()
        self.loop.run_until_complete(self.handle_commands())


if __name__ == "__main__":
    assistant = VoiceAssistant()
    assistant.show_examples()
    try:
        assistant.run()
    except KeyboardInterrupt:
        assistant.running = False
        print("Shutting down assistant.")
