# =====================================================
# MULTI SESSION TELEGRAM BOT (ULTIMATE FULL - FIXED)
# Aiogram 2.25.1 + Telethon
# RAILWAY 100% STABLE
# =====================================================

import os, asyncio, sqlite3, random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext

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

# ================= GLOBAL LOCKS =================
db_lock = asyncio.Lock()
session_locks = {}

def get_lock(session):
    if session not in session_locks:
        session_locks[session] = asyncio.Lock()
    return session_locks[session]

# ================= GLOBALS =================
approved_users = set()
pending_requests = {}
running_tasks = {}
running_clients = {}

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB, timeout=60, check_same_thread=False)

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

# ================= MENU =================
async def main_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📱 Raqamlar", "👥 Guruhlar")
    kb.add("✉️ Habar yuborish", "⛔ Stop")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# =====================================================
# ================= ADMIN TASDIQLASH ==================
# =====================================================
async def send_admin_request(uid):
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ok:{uid}"),
        types.InlineKeyboardButton("❌ Rad", callback_data=f"no:{uid}")
    )

    pending_requests[uid] = []
    for a in ADMINS:
        m = await bot.send_message(a, f"👤 User `{uid}` kirishni so‘radi", parse_mode="Markdown", reply_markup=kb)
        pending_requests[uid].append((a, m.message_id))

@dp.callback_query_handler(lambda c: c.data.startswith(("ok:", "no:")))
async def admin_decide(call: types.CallbackQuery):
    action, uid = call.data.split(":")
    uid = int(uid)

    if uid not in pending_requests:
        await call.answer("⛔")
        return

    for a, mid in pending_requests[uid]:
        try:
            await bot.edit_message_text("✔️ Yakunlandi", a, mid)
        except:
            pass

    if action == "ok":
        approved_users.add(uid)
        await bot.send_message(uid, "✅ Tasdiqlandingiz")
    else:
        await bot.send_message(uid, "❌ Rad etildingiz")

    del pending_requests[uid]
    await call.answer()

# ================= START =================
@dp.message_handler(commands=["start"])
async def start(msg):
    uid = msg.from_user.id
    if uid in ADMINS or uid in approved_users:
        await main_menu(msg)
    else:
        await send_admin_request(uid)
        await msg.answer("⏳ Admin tasdiqlashi kutilmoqda")

# =====================================================
# ================= 📱 RAQAMLAR =======================
# =====================================================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar", reply_markup=kb)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_num(msg):
    await msg.answer("📞 +998...")
    await AddNum.phone.set()

@dp.message_handler(state=AddNum.phone)
async def phone(msg, state):
    phone = msg.text.strip()
    session = phone.replace("+", "")
    lock = get_lock(session)

    async with lock:
        client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            await state.update_data(phone=phone, session=session, hash=sent.phone_code_hash)
            await AddNum.code.set()
            await msg.answer("📨 Kodni kiriting")
        finally:
            await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def code(msg, state):
    d = await state.get_data()
    lock = get_lock(d['session'])

    async with lock:
        client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
        await client.connect()
        try:
            await client.sign_in(d['phone'], msg.text, phone_code_hash=d['hash'])
        except SessionPasswordNeededError:
            await AddNum.password.set()
            await msg.answer("🔐 2FA parol")
            return
        finally:
            await client.disconnect()

    async with db_lock:
        with db() as c:
            c.execute("INSERT OR IGNORE INTO numbers VALUES (?,?)", (msg.from_user.id, d['session']))

    await state.finish()
    await msg.answer("✅ Ulandi")
    await main_menu(msg)

@dp.message_handler(state=AddNum.password)
async def password(msg, state):
    d = await state.get_data()
    lock = get_lock(d['session'])

    async with lock:
        client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
        await client.connect()
        await client.sign_in(password=msg.text)
        await client.disconnect()

    async with db_lock:
        with db() as c:
            c.execute("INSERT OR IGNORE INTO numbers VALUES (?,?)", (msg.from_user.id, d['session']))

    await state.finish()
    await msg.answer("✅ Ulandi")
    await main_menu(msg)

# =====================================================
# ================= 👥 GURUHLAR =======================
# =====================================================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups(msg):
    async with db_lock:
        with db() as c:
            sessions = c.execute("SELECT session FROM numbers WHERE user_id=?", (msg.from_user.id,)).fetchall()

    kb = types.InlineKeyboardMarkup()
    for s in sessions:
        kb.add(types.InlineKeyboardButton(s[0], callback_data=f"grp:{s[0]}"))
    await msg.answer("📂 Session tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("grp:"))
async def load_groups(call: types.CallbackQuery):
    sess = call.data.split(":")[1]
    lock = get_lock(sess)

    async with lock:
        client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
        await client.start()
        dialogs = await client.get_dialogs(limit=None)
        await client.disconnect()

    kb = types.InlineKeyboardMarkup()
    for d in dialogs:
        if d.is_group or d.is_channel:
            kb.add(types.InlineKeyboardButton(d.name[:30], callback_data=f"add:{sess}:{d.id}"))

    await call.message.edit_text("👥 Guruhlar", reply_markup=kb)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("add:"))
async def add_group(call: types.CallbackQuery):
    _, sess, gid = call.data.split(":")
    async with db_lock:
        with db() as c:
            c.execute(
                "INSERT OR IGNORE INTO selected_groups VALUES (?,?,?,?)",
                (call.from_user.id, sess, int(gid), "group")
            )
    await call.answer("✅ Qo‘shildi")

# =====================================================
# ================= ✉️ HABAR ==========================
# =====================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    async with db_lock:
        with db() as c:
            sessions = c.execute(
                "SELECT DISTINCT session FROM selected_groups WHERE user_id=?",
                (msg.from_user.id,)
            ).fetchall()

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for s in sessions:
        kb.add(s[0])
    kb.add("⬅️ Orqaga")

    await msg.answer("📂 Session tanlang", reply_markup=kb)
    await SendFlow.session.set()

@dp.message_handler(state=SendFlow.session)
async def send_text(msg, state):
    await state.update_data(session=msg.text)
    await msg.answer("✏️ Matn:")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_interval(msg, state):
    await state.update_data(text=msg.text)
    await msg.answer("⏱ Interval (min):")
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_send(msg, state):
    d = await state.get_data()
    interval = int(msg.text)

    async with db_lock:
        with db() as c:
            groups = c.execute(
                "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
                (msg.from_user.id, d['session'])
            ).fetchall()

    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.start()
    running_clients[msg.from_user.id] = client

    async def loop():
        while True:
            for g in groups:
                try:
                    await client.send_message(g[0], d['text'])
                    await asyncio.sleep(random.randint(8, 15))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds)
            await asyncio.sleep(interval * 60)

    running_tasks[msg.from_user.id] = asyncio.create_task(loop())
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await main_menu(msg)

# ================= STOP =================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop(msg):
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
