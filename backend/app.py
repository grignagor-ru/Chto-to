import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI
from pydantic import BaseModel

DB_PATH = os.getenv('FF_DB_PATH', 'focusflow.db')
BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '')

app = FastAPI(title='FocusFlow API')


def db():
  con = sqlite3.connect(DB_PATH)
  con.row_factory = sqlite3.Row
  return con


def init_db():
  con = db()
  cur = con.cursor()
  cur.execute('''
  CREATE TABLE IF NOT EXISTS states (
    user_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
  )''')
  cur.execute('''
  CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    text TEXT NOT NULL,
    sent INTEGER DEFAULT 0
  )''')
  con.commit()
  con.close()


class StatePayload(BaseModel):
  user_id: str
  todos: list[dict[str, Any]] = []
  focus_count: int = 0
  history: list[dict[str, Any]] = []
  timer: dict[str, Any] = {}


class ReminderPayload(BaseModel):
  user_id: str
  remind_at: str
  text: str


@app.get('/health')
def health():
  return {'ok': True}


@app.post('/state')
def put_state(payload: StatePayload):
  con = db()
  cur = con.cursor()
  import json
  cur.execute(
    'INSERT INTO states(user_id,payload,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at',
    (payload.user_id, json.dumps(payload.model_dump(), ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
  )
  con.commit()
  con.close()
  return {'ok': True}


@app.get('/state/{user_id}')
def get_state(user_id: str):
  con = db()
  cur = con.cursor()
  cur.execute('SELECT payload FROM states WHERE user_id=?', (user_id,))
  row = cur.fetchone()
  con.close()
  if not row:
    return {}
  import json
  return json.loads(row['payload'])


@app.post('/reminder')
def set_reminder(payload: ReminderPayload):
  con = db()
  cur = con.cursor()
  cur.execute('INSERT INTO reminders(user_id, remind_at, text, sent) VALUES(?,?,?,0)', (payload.user_id, payload.remind_at, payload.text))
  con.commit()
  con.close()
  return {'ok': True}


def send_telegram(chat_id: str, text: str):
  if not BOT_TOKEN or not chat_id.isdigit():
    return
  url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
  requests.post(url, json={'chat_id': int(chat_id), 'text': text}, timeout=10)


def reminder_worker():
  while True:
    con = db()
    cur = con.cursor()
    cur.execute('SELECT id, user_id, remind_at, text FROM reminders WHERE sent=0')
    rows = cur.fetchall()
    now = datetime.now(timezone.utc)
    for row in rows:
      try:
        remind_at = datetime.fromisoformat(row['remind_at'].replace('Z', '+00:00'))
      except ValueError:
        continue
      if remind_at <= now:
        send_telegram(row['user_id'], f'⏰ FocusFlow: {row["text"]}')
        cur.execute('UPDATE reminders SET sent=1 WHERE id=?', (row['id'],))
    con.commit()
    con.close()
    time.sleep(5)


@app.on_event('startup')
def startup_event():
  init_db()
  t = threading.Thread(target=reminder_worker, daemon=True)
  t.start()
