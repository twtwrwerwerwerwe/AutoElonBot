# =====================================================
# MULTI SESSION TELEGRAM BOT (STABLE FINAL VERSION)
# Aiogram 2.25.1 + Telethon
# =====================================================

import os, asyncio, sqlite3, random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError

# ================= CONFIG =================
BOT_TOKEN = "8291345152:AAEeOP-2U9AfYvwCFnxrwDoFg7sjyWGwqGk"
API_ID = 32460736
API_HASH = "285e2a8556652e6f4ffdb83658081031"

ADMINS = [6302873072, 6731395876]

DB = "bot.db"
SESS_DIR = "sessions"
os.makedirs(SESS_DIR, exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

running_tasks = {}
running_clients = {}

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB, timeout=30)

with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS numbers(
        user_id INTEGER,
        session TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS selected_groups(
        user_id INTEGER,
        session TEXT,
        group_id INTEGER
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

# ================= MENU =================
async def main_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📱 Raqamlar", "👥 Guruhlar")
    kb.add("✉️ Habar yuborish", "⛔ Stop")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# ================= START =================
@dp.message_handler(commands=["start"])
async def start(msg):
    if msg.from_user.id not in ADMINS:
        await msg.answer("⛔ Ruxsat yo‘q")
        return
    await main_menu(msg)

# =====================================================
# ================= RAQAM QO‘SHISH ====================
# =====================================================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg):
    await msg.answer("📞 Telefon raqam (+998...)")
    await AddNum.phone.set()

@dp.message_handler(state=AddNum.phone)
async def phone_step(msg, state):
    phone = msg.text.strip()
    session = phone.replace("+", "")

    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
    await client.connect()

    try:
        sent = await client.send_code_request(phone)
        await state.update_data(
            phone=phone,
            session=session,
            hash=sent.phone_code_hash
        )
        await AddNum.code.set()
        await msg.answer("📩 SMS kodni kiriting")
    except:
        await msg.answer("❌ Raqam xato yoki bloklangan")
        await state.finish()
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def code_step(msg, state):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()

    try:
        await client.sign_in(
            phone=d['phone'],
            code=msg.text,
            phone_code_hash=d['hash']
        )
    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2FA parolni kiriting")
        return
    except:
        await msg.answer("❌ Kod noto‘g‘ri")
        await state.finish()
        await client.disconnect()
        return

    with db() as c:
        c.execute("INSERT INTO numbers VALUES (?,?)",
                  (msg.from_user.id, d['session']))

    await client.disconnect()
    await state.finish()
    await msg.answer("✅ Akkaunt ulandi")
    await main_menu(msg)

@dp.message_handler(state=AddNum.password)
async def password_step(msg, state):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()

    try:
        await client.sign_in(password=msg.text)
    except:
        await msg.answer("❌ Parol xato, qayta kiriting")
        return

    with db() as c:
        c.execute("INSERT INTO numbers VALUES (?,?)",
                  (msg.from_user.id, d['session']))

    await client.disconnect()
    await state.finish()
    await msg.answer("✅ 2FA bilan ulandi")
    await main_menu(msg)

# =====================================================
# ================= GURUHLAR ==========================
# =====================================================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups_menu(msg):
    with db() as c:
        sessions = c.execute(
            "SELECT session FROM numbers WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchall()

    kb = types.InlineKeyboardMarkup()
    for (s,) in sessions:
        kb.add(types.InlineKeyboardButton(s, callback_data=f"grp:{s}"))

    await msg.answer("📂 Session tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("grp:"))
async def load_groups(call):
    sess = call.data.split(":")[1]

    async with TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH) as client:
        dialogs = await client.get_dialogs(limit=100)

    kb = types.InlineKeyboardMarkup(row_width=1)
    for d in dialogs:
        if d.is_group:
            kb.add(types.InlineKeyboardButton(
                d.name[:30],
                callback_data=f"addgrp:{sess}:{d.id}"
            ))

    await call.message.edit_text("👥 Guruhlar", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("addgrp:"))
async def add_group(call):
    _, sess, gid = call.data.split(":")

    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO selected_groups VALUES (?,?,?)",
            (call.from_user.id, sess, int(gid))
        )

    await call.answer("✅ Guruh qo‘shildi")

# =====================================================
# ================= HABAR YUBORISH ====================
# =====================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    await msg.answer("✏️ Habar matni")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_interval(msg, state):
    await state.update_data(text=msg.text)
    await msg.answer("⏱ Interval (daqiqa)")
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_sending(msg, state):
    d = await state.get_data()
    interval = int(msg.text)

    with db() as c:
        rows = c.execute(
            "SELECT session, group_id FROM selected_groups WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchall()

    async def loop():
        while True:
            for sess, gid in rows:
                try:
                    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
                    await client.start()
                    await client.send_message(gid, d['text'])
                    await asyncio.sleep(random.randint(20, 40))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
                finally:
                    await client.disconnect()
            await asyncio.sleep(interval * 60)

    running_tasks[msg.from_user.id] = asyncio.create_task(loop())
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await main_menu(msg)

# ================= STOP =================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop(msg):
    task = running_tasks.pop(msg.from_user.id, None)
    if task:
        task.cancel()
    await msg.answer("⛔ To‘xtatildi")
    await main_menu(msg)

# ================= RUN =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
