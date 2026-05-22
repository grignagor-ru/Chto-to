import asyncio
import os
import random
import sqlite3
import string
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)

DB_PATH = "anon_chat.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            age_group TEXT,
            interests TEXT,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            age_group TEXT,
            interests TEXT,
            text TEXT NOT NULL,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS dialogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            guest_id INTEGER NOT NULL,
            created_at TEXT,
            UNIQUE(post_id, guest_id)
        )
        """
    )

    conn.commit()
    conn.close()


def save_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
        (user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def set_profile(user_id: int, age_group: Optional[str], interests: Optional[str]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users(user_id, age_group, interests, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET age_group=excluded.age_group, interests=excluded.interests
        """,
        (user_id, age_group, interests, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def generate_alias():
    return "Anon-" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(5))


def create_post(author_id: int, text: str):
    user = get_user(author_id)
    age_group = user["age_group"] if user else None
    interests = user["interests"] if user else None

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO posts(author_id, alias, age_group, interests, text, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            author_id,
            generate_alias(),
            age_group,
            interests,
            text,
            datetime.utcnow().isoformat(),
        ),
    )
    post_id = cur.lastrowid
    conn.commit()
    conn.close()
    return post_id


def get_feed(age_group: Optional[str] = None, interest: Optional[str] = None, limit: int = 10):
    conn = get_conn()
    cur = conn.cursor()

    query = "SELECT * FROM posts WHERE 1=1"
    args = []
    if age_group:
        query += " AND (age_group=? OR age_group IS NULL)"
        args.append(age_group)
    if interest:
        query += " AND (interests LIKE ? OR interests IS NULL)"
        args.append(f"%{interest}%")

    query += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    cur.execute(query, args)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_post(post_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM posts WHERE id=?", (post_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_or_create_dialog(post_id: int, author_id: int, guest_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO dialogs(post_id, author_id, guest_id, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (post_id, author_id, guest_id, datetime.utcnow().isoformat()),
    )
    conn.commit()

    cur.execute(
        "SELECT * FROM dialogs WHERE post_id=? AND guest_id=?",
        (post_id, guest_id),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_dialog(dialog_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM dialogs WHERE id=?", (dialog_id,))
    row = cur.fetchone()
    conn.close()
    return row


def main_menu():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Новый анонимный пост", callback_data="new_post")],
            [InlineKeyboardButton(text="🗂 Лента постов", callback_data="feed")],
            [InlineKeyboardButton(text="⚙️ Профиль (возраст/интересы)", callback_data="profile")],
        ]
    )


awaiting_post = set()
awaiting_profile = set()
active_dialog_reply = {}


async def on_start(message: Message):
    save_user(message.from_user.id)
    await message.answer(
        "Привет! Это анонимная площадка.\n"
        "— Публикуй анонимные посты\n"
        "— Пиши авторам в приватный диалог\n"
        "— Фильтруй ленту по возрасту и интересам\n\n"
        "Используй кнопки ниже:",
        reply_markup=main_menu(),
    )


async def on_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/start — меню\n"
        "/newpost — создать пост\n"
        "/feed — открыть ленту\n"
        "/profile — настроить возраст и интересы\n\n"
        "Для ответа в диалоге: /reply <dialog_id> <текст>"
    )


async def on_new_post_cmd(message: Message):
    awaiting_post.add(message.from_user.id)
    await message.answer("Отправь текст поста одним сообщением.")


async def on_profile_cmd(message: Message):
    awaiting_profile.add(message.from_user.id)
    await message.answer(
        "Отправь профиль в формате:\n"
        "<возрастная_группа>; <интересы через запятую>\n"
        "Пример: 18-24; музыка, IT, спорт"
    )


async def on_feed_cmd(message: Message):
    user = get_user(message.from_user.id)
    age = user["age_group"] if user else None
    interest = None
    if user and user["interests"]:
        interest = user["interests"].split(",")[0].strip()
    rows = get_feed(age_group=age, interest=interest)
    if not rows:
        await message.answer("Пока постов нет. Создай первый через /newpost")
        return

    for p in rows:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💬 Написать автору",
                        callback_data=f"msg_author:{p['id']}",
                    )
                ]
            ]
        )
        await message.answer(
            f"Пост #{p['id']}\n"
            f"Автор: {p['alias']}\n"
            f"Возраст: {p['age_group'] or 'не указан'}\n"
            f"Интересы: {p['interests'] or 'не указаны'}\n\n"
            f"{p['text']}",
            reply_markup=kb,
        )


async def on_main_callbacks(call: CallbackQuery):
    if call.data == "new_post":
        awaiting_post.add(call.from_user.id)
        await call.message.answer("Отправь текст поста одним сообщением.")
    elif call.data == "feed":
        dummy = Message.model_validate(call.message.model_dump())
        dummy.from_user = call.from_user
        await on_feed_cmd(dummy)
    elif call.data == "profile":
        awaiting_profile.add(call.from_user.id)
        await call.message.answer(
            "Отправь профиль в формате:\n"
            "<возрастная_группа>; <интересы через запятую>"
        )
    await call.answer()


async def on_msg_author(call: CallbackQuery):
    post_id = int(call.data.split(":")[1])
    post = get_post(post_id)
    if not post:
        await call.answer("Пост не найден", show_alert=True)
        return
    if post["author_id"] == call.from_user.id:
        await call.answer("Это твой пост 🙂", show_alert=True)
        return

    dialog = get_or_create_dialog(post_id, post["author_id"], call.from_user.id)
    active_dialog_reply[call.from_user.id] = dialog["id"]

    bot = call.bot
    await bot.send_message(
        post["author_id"],
        f"Тебе написал читатель по посту #{post_id}.\n"
        f"Dialog ID: {dialog['id']}\n"
        f"Чтобы ответить: /reply {dialog['id']} <текст>",
    )

    await call.message.answer(
        f"Диалог создан. Dialog ID: {dialog['id']}\n"
        f"Напиши сообщение и оно анонимно уйдет автору."
    )
    await call.answer()


async def on_reply_cmd(message: Message):
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /reply <dialog_id> <текст>")
        return
    try:
        dialog_id = int(parts[1])
    except ValueError:
        await message.answer("dialog_id должен быть числом")
        return
    text = parts[2]

    dialog = get_dialog(dialog_id)
    if not dialog:
        await message.answer("Диалог не найден")
        return

    if message.from_user.id not in (dialog["author_id"], dialog["guest_id"]):
        await message.answer("Это не твой диалог")
        return

    to_user = dialog["guest_id"] if message.from_user.id == dialog["author_id"] else dialog["author_id"]
    await message.bot.send_message(to_user, f"💬 Новое анонимное сообщение (dialog {dialog_id}):\n{text}")
    await message.answer("Отправлено ✅")


async def on_plain_text(message: Message):
    uid = message.from_user.id

    if uid in awaiting_post:
        post_id = create_post(uid, message.text)
        awaiting_post.discard(uid)
        await message.answer(f"Пост опубликован ✅ ID: {post_id}", reply_markup=main_menu())
        return

    if uid in awaiting_profile:
        awaiting_profile.discard(uid)
        try:
            age, interests = [x.strip() for x in message.text.split(";", maxsplit=1)]
        except ValueError:
            await message.answer("Неверный формат. Пример: 18-24; музыка, IT, спорт")
            return
        set_profile(uid, age, interests)
        await message.answer("Профиль обновлен ✅", reply_markup=main_menu())
        return

    if uid in active_dialog_reply:
        dialog_id = active_dialog_reply[uid]
        dialog = get_dialog(dialog_id)
        if dialog:
            to_user = dialog["author_id"]
            await message.bot.send_message(
                to_user,
                f"💬 Сообщение от читателя (dialog {dialog_id}):\n{message.text}\n"
                f"Для ответа: /reply {dialog_id} <текст>",
            )
            await message.answer("Сообщение отправлено автору ✅")
            return

    await message.answer("Не понял команду. Нажми /start")


async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан BOT_TOKEN в переменных окружения")

    init_db()

    bot = Bot(token)
    dp = Dispatcher()

    dp.message.register(on_start, CommandStart())
    dp.message.register(on_help, Command("help"))
    dp.message.register(on_new_post_cmd, Command("newpost"))
    dp.message.register(on_feed_cmd, Command("feed"))
    dp.message.register(on_profile_cmd, Command("profile"))
    dp.message.register(on_reply_cmd, Command("reply"))

    dp.callback_query.register(on_main_callbacks, F.data.in_({"new_post", "feed", "profile"}))
    dp.callback_query.register(on_msg_author, F.data.startswith("msg_author:"))

    dp.message.register(on_plain_text, F.text)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
