# =====================================================
# MULTI SESSION TELEGRAM BOT (ANTI FLOOD + FIXED)
# Aiogram 2.25.1 + Telethon
# =====================================================

import os
import asyncio
import sqlite3
import random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

# ================= CONFIG =================
BOT_TOKEN = "TOKEN"
API_ID = 32460736
API_HASH = "HASH"

ADMINS = [6302873072, 6731395876]

DB = "bot.db"
SESS_DIR = "sessions"
os.makedirs(SESS_DIR, exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================= GLOBALS =================
approved_users = set()
pending_requests = {}
running_tasks = {}
running_clients = {}

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB, timeout=30)

with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS numbers(
        user_id INTEGER,
        session TEXT UNIQUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS selected_groups(
        user_id INTEGER,
        session TEXT,
        group_id INTEGER,
        title TEXT
    )""")

# ================= STATES =================
class AddNum(StatesGroup):
    phone = State()
    code = State()
    password = State()

class SendFlow(StatesGroup):
    session = State()
    text = State()
    interval = State()

# ================= HELPERS =================
async def back_to_menu(msg, state=None):
    if state:
        await state.finish()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📱 Raqamlar", "👥 Guruhlar")
    kb.add("✉️ Habar yuborish", "⛔ Stop")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# GLOBAL BACK HANDLER (HAR JOYDA ISHLAYDI)
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", state="*")
async def universal_back(msg: types.Message, state: FSMContext):
    await back_to_menu(msg, state)

# =====================================================
# ================= START =================
# =====================================================
@dp.message_handler(commands=["start"])
async def start(msg):
    if msg.from_user.id in ADMINS or msg.from_user.id in approved_users:
        await back_to_menu(msg)
    else:
        await msg.answer("⏳ Admin tasdiqlashi kutilmoqda")

# =====================================================
# ================= 📱 RAQAMLAR =================
# =====================================================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg):
    await msg.answer("📞 Telefon raqam kiriting\n(+998...)")
    await AddNum.phone.set()

@dp.message_handler(state=AddNum.phone)
async def get_phone(msg, state):
    phone = msg.text.strip()
    session = phone.replace("+", "")

    client = TelegramClient(
        os.path.join(SESS_DIR, session),
        API_ID,
        API_HASH
    )

    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        await state.update_data(
            phone=phone,
            session=session,
            phone_code_hash=sent.phone_code_hash
        )
        await AddNum.code.set()
        await msg.answer("📩 SMS kodni kiriting:")
    except Exception as e:
        await msg.answer("❌ Kod yuborilmadi. Raqam bloklangan bo‘lishi mumkin.")
        await state.finish()
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def get_code(msg, state):
    data = await state.get_data()
    client = TelegramClient(os.path.join(SESS_DIR, data["session"]), API_ID, API_HASH)
    await client.connect()

    try:
        await client.sign_in(
            phone=data["phone"],
            code=msg.text.strip(),
            phone_code_hash=data["phone_code_hash"]
        )
    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2FA parolni kiriting:")
        return
    except Exception:
        await msg.answer("❌ Kod xato")
        await state.finish()
        await client.disconnect()
        return

    with db() as c:
        c.execute("INSERT OR IGNORE INTO numbers VALUES (?,?)",
                  (msg.from_user.id, data["session"]))

    await client.disconnect()
    await msg.answer("✅ Akkaunt ulandi")
    await state.finish()
    await back_to_menu(msg)

@dp.message_handler(state=AddNum.password)
async def get_password(msg, state):
    data = await state.get_data()
    client = TelegramClient(os.path.join(SESS_DIR, data["session"]), API_ID, API_HASH)
    await client.connect()

    try:
        await client.sign_in(password=msg.text.strip())
        with db() as c:
            c.execute("INSERT OR IGNORE INTO numbers VALUES (?,?)",
                      (msg.from_user.id, data["session"]))
        await msg.answer("✅ Akkaunt ulandi")
    except:
        await msg.answer("❌ Parol xato")
        return
    finally:
        await client.disconnect()

    await state.finish()
    await back_to_menu(msg)

# =====================================================
# ================= ✉️ HABAR YUBORISH (ANTI FLOOD) =================
# =====================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    with db() as c:
        sessions = c.execute(
            "SELECT session FROM numbers WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchall()

    if not sessions:
        await msg.answer("❌ Avval raqam qo‘shing")
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for (s,) in sessions:
        kb.add(s)
    kb.add("⬅️ Orqaga")

    await msg.answer("📂 Session tanlang:", reply_markup=kb)
    await SendFlow.session.set()

@dp.message_handler(state=SendFlow.session)
async def send_text(msg, state):
    await state.update_data(session=msg.text)
    await msg.answer("✏️ Habar matnini kiriting:")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_interval(msg, state):
    await state.update_data(text=msg.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("5", "10", "15", "20")
    kb.add("⬅️ Orqaga")
    await msg.answer("⏱ Interval (daqiqada):", reply_markup=kb)
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_sender(msg, state):
    interval = int(msg.text)
    data = await state.get_data()

    with db() as c:
        groups = c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (msg.from_user.id, data["session"])
        ).fetchall()

    client = TelegramClient(
        os.path.join(SESS_DIR, data["session"]),
        API_ID,
        API_HASH
    )
    await client.start()
    running_clients[msg.from_user.id] = client

    async def sender():
        while True:
            for (gid,) in groups:
                try:
                    await client.send_message(gid, data["text"])
                    await asyncio.sleep(random.randint(15, 30))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 5)
            await asyncio.sleep(interval * 60)

    running_tasks[msg.from_user.id] = asyncio.create_task(sender())
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await back_to_menu(msg)

# =====================================================
# ================= STOP =================
# =====================================================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop_all(msg):
    task = running_tasks.pop(msg.from_user.id, None)
    client = running_clients.pop(msg.from_user.id, None)

    if task:
        task.cancel()
    if client:
        await client.disconnect()

    await msg.answer("⛔ To‘xtatildi")
    await back_to_menu(msg)

# ================= RUN =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
