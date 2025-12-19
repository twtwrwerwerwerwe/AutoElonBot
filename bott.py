import os
import asyncio
import sqlite3
import random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# ================= CONFIG =================
BOT_TOKEN = "8291345152:AAEeOP-2U9AfYvwCFnxrwDoFg7sjyWGwqGk"
API_ID = 32460736
API_HASH = "285e2a8556652e6f4ffdb83658081031"
ADMINS = [6302873072, 6731395876]  # admin id lar
DB = "bot.db"
SESS_DIR = "sessions"
os.makedirs(SESS_DIR, exist_ok=True)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB, timeout=30)

with db() as c:
    c.execute("""CREATE TABLE IF NOT EXISTS numbers(user_id INTEGER, session TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS selected_groups(user_id INTEGER, session TEXT, group_id INTEGER, title TEXT)""")

# ================= STATES =================
class AddNum(StatesGroup):
    phone = State()
    code = State()
    password = State()

class SendFlow(StatesGroup):
    session = State()
    text = State()
    interval = State()

# ================= GLOBALS =================
approved_users = set()
pending_requests = {}
running_tasks = {}
running_clients = {}

# ================= ADMIN TASDIQLASH =================
async def send_admin_request(user_id):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{user_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{user_id}")
    )
    pending_requests[user_id] = []
    for admin in ADMINS:
        m = await bot.send_message(
            admin,
            f"👤 Foydalanuvchi `{user_id}` botga kirishni so‘rayapti",
            parse_mode="Markdown",
            reply_markup=kb
        )
        pending_requests[user_id].append((admin, m.message_id))

@dp.callback_query_handler(lambda c: c.data.startswith(("approve:", "reject:")))
async def admin_decision(call: types.CallbackQuery):
    action, uid = call.data.split(":")
    uid = int(uid)
    if uid not in pending_requests:
        await call.answer("⛔ Allaqachon hal qilingan")
        return
    text = "✅ Tasdiqlandi" if action == "approve" else "❌ Rad etildi"
    for admin_id, msg_id in pending_requests[uid]:
        try:
            await bot.edit_message_text(text, admin_id, msg_id)
        except:
            pass
    if action == "approve":
        approved_users.add(uid)
        await bot.send_message(uid, "✅ Siz tasdiqlandingiz. Botdan foydalanishingiz mumkin.")
    else:
        await bot.send_message(uid, "❌ Siz admin tomonidan rad etildingiz.")
    del pending_requests[uid]
    await call.answer("✔️ Bajarildi")

# ================= START =================
@dp.message_handler(commands=["start"])
async def start(msg):
    uid = msg.from_user.id
    if uid in ADMINS or uid in approved_users:
        await main_menu(msg)
    else:
        await send_admin_request(uid)
        await msg.answer("⏳ Adminlar tasdiqlashini kuting...")

# ================= MENU =================
async def main_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📱 Raqamlar", "👥 Guruhlar")
    kb.add("✉️ Habar yuborish", "⛔ Stop")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# ================= 📱 RAQAMLAR =================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar bo‘limi", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg):
    await msg.answer("📞 Telefon raqam kiriting (+998...)")
    await AddNum.phone.set()

@dp.message_handler(state=AddNum.phone)
async def get_phone(msg, state):
    phone = msg.text.strip()
    session = phone.replace("+", "")
    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        await state.update_data(phone=phone, session=session, hash=sent.phone_code_hash)
        await AddNum.code.set()
        await msg.answer("📨 SMS kodni kiriting:")
    except Exception as e:
        await msg.answer(f"❌ Raqam xato yoki bloklangan: {e}")
        await state.finish()
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def get_code(msg, state):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(d['phone'], msg.text, phone_code_hash=d['hash'])
    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2-bosqichli parolni kiriting:")
        return
    except Exception as e:
        await msg.answer(f"❌ Kod xato: {e}")
        await state.finish()
        await client.disconnect()
        return
    with db() as c:
        c.execute("INSERT INTO numbers VALUES (?,?)", (msg.from_user.id, d['session']))
    await client.disconnect()
    await msg.answer("✅ Akkaunt ulandi")
    await state.finish()
    await main_menu(msg)

@dp.message_handler(state=AddNum.password)
async def get_password(msg, state):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(password=msg.text)
        with db() as c:
            c.execute("INSERT INTO numbers VALUES (?,?)", (msg.from_user.id, d['session']))
        await msg.answer("✅ Akkaunt ulandi")
    except Exception as e:
        await msg.answer(f"❌ Parol noto‘g‘ri: {e}")
        return
    finally:
        await client.disconnect()
    await state.finish()
    await main_menu(msg)

# ================= GURUHLAR =================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups_menu(msg):
    with db() as c:
        sessions = c.execute("SELECT session FROM numbers WHERE user_id=?", (msg.from_user.id,)).fetchall()
    if not sessions:
        await msg.answer("❌ Sizda session yo‘q")
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for s in sessions:
        kb.add(s[0])
    kb.add("⬅️ Orqaga")
    await msg.answer("📂 Session tanlang", reply_markup=kb)

# ================= SEND FLOW =================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    with db() as c:
        sessions = c.execute("SELECT DISTINCT session FROM selected_groups WHERE user_id=?", (msg.from_user.id,)).fetchall()
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for s in sessions:
        kb.add(s[0])
    kb.add("⬅️ Orqaga")
    await msg.answer("📂 Session tanlang", reply_markup=kb)
    await SendFlow.session.set()

@dp.message_handler(state=SendFlow.session)
async def get_text(msg, state):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return
    await state.update_data(session=msg.text)
    await msg.answer("✏️ Habar matni:")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def get_interval(msg, state):
    await state.update_data(text=msg.text)
    await msg.answer("⏱ Interval (min): 5 / 10 / 15")
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_sending(msg, state):
    d = await state.get_data()
    try:
        interval = int(msg.text)
    except:
        await msg.answer("❌ Iltimos, son kiriting (5, 10, 15)")
        return
    with db() as c:
        groups = c.execute("SELECT group_id FROM selected_groups WHERE user_id=? AND session=?", (msg.from_user.id, d['session'])).fetchall()
    if not groups:
        await msg.answer("❌ Hech qanday guruh tanlanmagan")
        await state.finish()
        await main_menu(msg)
        return
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.start()
    running_clients[msg.from_user.id] = client

    async def loop():
        while True:
            for g in groups:
                try:
                    await client.send_message(g[0], d['text'])
                    await asyncio.sleep(random.randint(7, 15))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
            await asyncio.sleep(interval*60)
    running_tasks[msg.from_user.id] = asyncio.create_task(loop())
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await main_menu(msg)

# ================= STOP =================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop_all(msg):
    task = running_tasks.pop(msg.from_user.id, None)
    client = running_clients.pop(msg.from_user.id, None)
    if task:
        task.cancel()
    if client:
        await client.disconnect()
    await msg.answer("⛔ To‘xtatildi")
    await main_menu(msg)

# ================= RUN =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
