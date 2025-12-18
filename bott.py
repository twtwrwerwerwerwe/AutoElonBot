# =====================================================
# MULTI SESSION TELEGRAM BOT (ULTIMATE FULL)
# Aiogram 2.25.1 + Telethon
# =====================================================

import os, asyncio, sqlite3, random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError
)

# ================= CONFIG =================
BOT_TOKEN = "8291345152:AAEeOP-2U9AfYvwCFnxrwDoFg7sjyWGwqGk"
API_ID = 32460736
API_HASH = "285e2a8556652e6f4ffdb83658081031"

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
    c.execute("""CREATE TABLE IF NOT EXISTS groups(
        user_id INTEGER,
        session TEXT,
        group_id INTEGER,
        title TEXT
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

class GroupFlow(StatesGroup):
    session = State()

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

# ================= RESET / START =================
@dp.message_handler(commands=['start'])
async def start(msg: types.Message, state: FSMContext):
    await state.finish()
    task = running_tasks.pop(msg.from_user.id, None)
    client = running_clients.pop(msg.from_user.id, None)
    if task:
        task.cancel()
    if client:
        await client.disconnect()
    await main_menu(msg)

# =================================================
# ================= 📱 RAQAMLAR ==================
# =================================================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar bo‘limi", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def ask_phone(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("❌ Bekor qilish")
    await msg.answer("📞 Telefon raqam kiriting (+998...)", reply_markup=kb)
    await AddNum.phone.set()

@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", state="*")
async def back_menu(msg, state: FSMContext):
    await state.finish()
    await main_menu(msg)

@dp.message_handler(lambda m: m.text == "❌ Bekor qilish", state="*")
async def cancel_any(msg, state: FSMContext):
    await state.finish()
    await msg.answer("❌ Bekor qilindi")
    await main_menu(msg)

@dp.message_handler(state=AddNum.phone)
async def get_phone(msg, state: FSMContext):
    phone = msg.text.strip()
    session = phone.replace("+", "")
    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        await state.update_data(
            phone=phone,
            session=session,
            code_hash=sent.phone_code_hash
        )
        await msg.answer("📨 SMS kodni kiriting:")
        await AddNum.code.set()
    except Exception:
        await msg.answer("❌ Ulanib bo‘lmadi yoki raqam xato")
        await state.finish()
        await main_menu(msg)
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def get_code(msg, state: FSMContext):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(phone=d['phone'], code=msg.text, phone_code_hash=d['code_hash'])
        with db() as c:
            c.execute("INSERT INTO numbers(user_id,session) VALUES (?,?)",(msg.from_user.id, d['session']))
        await msg.answer("✅ Raqam muvaffaqiyatli ulandi")
    except SessionPasswordNeededError:
        await msg.answer("🔐 2 bosqichli parolni kiriting:")
        await AddNum.password.set()
        return
    except Exception:
        await msg.answer("❌ Kod xato yoki akkaunt bloklangan")
        await state.finish()
        await main_menu(msg)
        return
    finally:
        await client.disconnect()
    await state.finish()
    await main_menu(msg)

@dp.message_handler(state=AddNum.password)
async def get_password(msg, state: FSMContext):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(password=msg.text)
        with db() as c:
            c.execute("INSERT INTO numbers(user_id,session) VALUES (?,?)",(msg.from_user.id, d['session']))
        await msg.answer("✅ Parol to‘g‘ri, akkaunt ulandi")
    except Exception:
        await msg.answer("❌ Parol xato yoki akkaunt bloklangan")
    finally:
        await client.disconnect()
    await state.finish()
    await main_menu(msg)

# =================================================
# ================= 👥 GURUHLAR =================
# =================================================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def choose_session(msg):
    with db() as c:
        rows = c.execute("SELECT session FROM numbers WHERE user_id=?",(msg.from_user.id,)).fetchall()
    kb = types.InlineKeyboardMarkup()
    for s in rows:
        kb.add(types.InlineKeyboardButton(text=s[0], callback_data=f"gs:{s[0]}"))
    kb.add(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main"))
    await msg.answer("📂 Session tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "back_main")
async def back_main(call: types.CallbackQuery):
    await call.message.delete()
    await main_menu(call.message)

@dp.callback_query_handler(lambda c: c.data.startswith("gs:"))
async def load_groups(call: types.CallbackQuery):
    sess = call.data.split(":")[1]
    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
    await client.start()
    with db() as c:
        c.execute("DELETE FROM groups WHERE user_id=? AND session=?",(call.from_user.id, sess))
        dialogs = await client.get_dialogs()
        kb = types.InlineKeyboardMarkup()
        for d in dialogs:
            if d.is_group or d.is_channel:
                c.execute("INSERT INTO groups(user_id,session,group_id,title) VALUES (?,?,?,?)",
                          (call.from_user.id, sess, d.id, d.name))
                kb.add(types.InlineKeyboardButton(text=d.name[:30], callback_data=f"gadd:{sess}:{d.id}"))
        kb.add(types.InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_main"))
    await client.disconnect()
    await call.message.edit_text("☑️ Guruh tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("gadd:"))
async def add_group(call: types.CallbackQuery):
    _, sess, gid = call.data.split(":")
    with db() as c:
        c.execute("INSERT INTO selected_groups(user_id,session,group_id) VALUES (?,?,?)",
                  (call.from_user.id, sess, int(gid)))
    await call.answer("✅ Guruh qo‘shildi")

# =================================================
# ================= ✉️ HABAR YUBORISH =================
# =================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_choose(msg):
    with db() as c:
        rows = c.execute("SELECT DISTINCT session FROM selected_groups WHERE user_id=?",(msg.from_user.id,)).fetchall()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for r in rows:
        kb.add(r[0])
    kb.add("⬅️ Orqaga")
    await msg.answer("📂 Session tanlang", reply_markup=kb)
    await SendFlow.session.set()

@dp.message_handler(state=SendFlow.session)
async def send_text(msg, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return
    await state.update_data(session=msg.text)
    await msg.answer("✏️ Habar matni:")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_interval(msg, state: FSMContext):
    await state.update_data(text=msg.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("5","10","15")
    await msg.answer("⏱ Interval (min)", reply_markup=kb)
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_send(msg, state: FSMContext):
    d = await state.get_data()
    mins = int(msg.text)
    with db() as c:
        groups = c.execute("SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
                           (msg.from_user.id, d['session'])).fetchall()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.start()
    running_clients[msg.from_user.id] = client

    async def loop():
        while True:
            for g in groups:
                try:
                    await client.send_message(g[0], d['text'])
                    await asyncio.sleep(random.randint(5,10))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
            await asyncio.sleep(mins*60)

    task = asyncio.create_task(loop())
    running_tasks[msg.from_user.id] = task
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await main_menu(msg)

# =================================================
# ================= ⛔ STOP =======================
# =================================================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop_all(msg):
    task = running_tasks.pop(msg.from_user.id, None)
    client = running_clients.pop(msg.from_user.id, None)
    if task:
        task.cancel()
    if client:
        await client.disconnect()
    await msg.answer("⛔ Yuborish to‘xtatildi")
    await main_menu(msg)

# ================= RUN =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
