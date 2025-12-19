# =====================================================
# MULTI SESSION TELEGRAM BOT (ULTIMATE FULL - FIXED + ANTI FLOOD)
# Aiogram 2.25.1 + Telethon
# =====================================================

import os, asyncio, sqlite3, random
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
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

# ================= GLOBALS =================
approved_users = set()
pending_requests = {}      # user_id -> [(admin_id, msg_id)]
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
            f"👤 Foydalanuvchi <a href='tg://user?id={user_id}'>{user_id}</a> botga kirishni so‘rayapti",
            parse_mode="HTML",
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

    # Inline tugmalarni HAMMA ADMINDAN o‘chirish
    for admin_id, msg_id in pending_requests[uid]:
        try:
            await bot.edit_message_text(
                text,
                admin_id,
                msg_id
            )
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

# =====================================================
# ================= 📱 RAQAMLAR =======================
# =====================================================
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
        await msg.answer(f"❌ Raqam xato yoki bloklangan ({e})")
        await state.finish()
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def get_code(msg, state):
    d = await state.get_data()
    client = TelegramClient(f"{SESS_DIR}/{d['session']}", API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(d['phone'], msg.text.strip(), phone_code_hash=d['hash'])
    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2-bosqichli parolni kiriting:")
        return
    except Exception as e:
        await msg.answer(f"❌ Kod xato ({e})")
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
        await client.sign_in(password=msg.text.strip())
        with db() as c:
            c.execute("INSERT INTO numbers VALUES (?,?)", (msg.from_user.id, d['session']))
        await msg.answer("✅ Akkaunt ulandi")
    except:
        await msg.answer("❌ Parol noto‘g‘ri, qayta urinib ko‘ring")
        return
    finally:
        await client.disconnect()

    await state.finish()
    await main_menu(msg)

# ================= SESSION O‘CHIRISH =================
@dp.message_handler(lambda m: m.text == "🗑 Raqam o‘chirish")
async def delete_session(msg):
    with db() as c:
        rows = c.execute("SELECT session FROM numbers WHERE user_id=?", (msg.from_user.id,)).fetchall()

    kb = types.InlineKeyboardMarkup()
    for s in rows:
        kb.add(types.InlineKeyboardButton(f"❌ {s[0]}", callback_data=f"delsess:{s[0]}"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back"))

    await msg.answer("🗑 O‘chiriladigan sessionni tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("delsess:"))
async def confirm_delete(call: types.CallbackQuery):
    sess = call.data.split(":")[1]

    if call.from_user.id in running_tasks:
        running_tasks[call.from_user.id].cancel()

    if call.from_user.id in running_clients:
        await running_clients[call.from_user.id].disconnect()

    with db() as c:
        c.execute("DELETE FROM numbers WHERE session=?", (sess,))
        c.execute("DELETE FROM selected_groups WHERE session=?", (sess,))

    try:
        os.remove(f"{SESS_DIR}/{sess}.session")
    except:
        pass

    await call.message.edit_text("✅ Session o‘chirildi")

# =====================================================
# ================= 👥 GURUHLAR =======================
# =====================================================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups_menu(msg):
    with db() as c:
        sessions = c.execute("SELECT session FROM numbers WHERE user_id=?", (msg.from_user.id,)).fetchall()

    kb = types.InlineKeyboardMarkup()
    for s in sessions:
        kb.add(types.InlineKeyboardButton(s[0], callback_data=f"loadgrp:{s[0]}"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back"))

    await msg.answer("📂 Session tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("loadgrp:"))
async def load_groups(call: types.CallbackQuery):
    sess = call.data.split(":")[1]
    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
    await client.start()

    dialogs = await client.get_dialogs(limit=100)

    with db() as c:
        added = {g[0] for g in c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (call.from_user.id, sess)
        )}

    kb = types.InlineKeyboardMarkup(row_width=1)
    for d in dialogs:
        if d.is_group or d.is_channel:
            mark = "✅ " if d.id in added else ""
            kb.add(types.InlineKeyboardButton(
                f"{mark}{d.name[:30]}",
                callback_data=f"addgrp:{sess}:{d.id}"
            ))

    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back"))
    await call.message.edit_text("👥 Guruhlar ro‘yxati", reply_markup=kb)
    await client.disconnect()

@dp.callback_query_handler(lambda c: c.data.startswith("addgrp:"))
async def toggle_group(call: types.CallbackQuery):
    _, sess, gid = call.data.split(":")
    gid = int(gid)
    user_id = call.from_user.id

    with db() as c:
        row = c.execute(
            "SELECT 1 FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
            (user_id, sess, gid)
        ).fetchone()

    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
    await client.start()
    entity = await client.get_entity(gid)
    title = entity.title
    await client.disconnect()

    if row:
        # ❌ olib tashlash
        with db() as c:
            c.execute(
                "DELETE FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
                (user_id, sess, gid)
            )
        prefix = ""
        await call.answer("❌ Olib tashlandi")
    else:
        # ✅ qo‘shish
        with db() as c:
            c.execute(
                "INSERT INTO selected_groups VALUES (?,?,?,?)",
                (user_id, sess, gid, title)
            )
        prefix = "✅ "
        await call.answer("✅ Tanlandi")

    # 🔁 TUGMANI YANGILASH
    kb = call.message.reply_markup
    for row_btn in kb.inline_keyboard:
        btn = row_btn[0]
        if btn.callback_data == call.data:
            btn.text = prefix + title[:30]

    await call.message.edit_reply_markup(reply_markup=kb)

# =====================================================
# ================= ✉️ HABAR YUBORISH =================
# =====================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    with db() as c:
        sessions = c.execute(
            "SELECT session FROM numbers WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchall()

    if not sessions:
        await msg.answer("❌ Avval session qo‘shing")
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for (sess,) in sessions:
        kb.add(sess)
    kb.add("⬅️ Orqaga")

    await msg.answer("📂 Session tanlang:", reply_markup=kb)
    await SendFlow.session.set()

@dp.message_handler(state=SendFlow.session)
async def send_get_text(msg, state):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return

    await state.update_data(session=msg.text)
    await msg.answer("✏️ Habar matnini kiriting:")
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_choose_interval(msg, state):
    await state.update_data(text=msg.text)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⏱ 5", "⏱ 10")
    kb.add("⏱ 15", "⏱ 20")
    kb.add("⬅️ Orqaga")

    await msg.answer("⏱ Intervalni tanlang (daqiqada):", reply_markup=kb)
    await SendFlow.interval.set()

@dp.message_handler(state=SendFlow.interval)
async def start_sending(msg, state):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return

    interval = int(msg.text.replace("⏱", "").strip())
    data = await state.get_data()

    session = data["session"]
    text = data["text"]
    user_id = msg.from_user.id

    with db() as c:
        groups = c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (user_id, session)
        ).fetchall()

    if not groups:
        await msg.answer("❌ Guruh tanlanmagan")
        return

    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
    await client.start()
    running_clients[user_id] = client

    async def loop():
        while True:
            for (gid,) in groups:
                try:
                    await client.send_message(gid, text)
                    await asyncio.sleep(random.randint(15, 30))  # ANTI FLOOD
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 5)
            await asyncio.sleep(interval * 60)

    running_tasks[user_id] = asyncio.create_task(loop())

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
