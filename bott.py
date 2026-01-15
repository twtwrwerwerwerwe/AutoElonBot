import os
import sys
import logging
import asyncio
import sqlite3
import random
import datetime

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError, UserIsBlockedError

import logging

# Asosiy logging ERROR va CRITICAL darajaga
logging.basicConfig(level=logging.ERROR)

# Aiogram faqat ERROR va CRITICAL ko‘rsatsin
logging.getLogger("aiogram").setLevel(logging.ERROR)

# Telethon faqat ERROR va CRITICAL ko‘rsatsin
logging.getLogger("telethon").setLevel(logging.ERROR)

# Ustiga qo'shimcha: aiogram update loglarini to‘liq o‘chirish
logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)


# ================= CONFIG =================
BOT_TOKEN = "8396193031:AAGzjseC_1qASNy6bWNkI4BTQnRXaiGV6eg"
API_ID = 32460736
API_HASH = "285e2a8556652e6f4ffdb83658081031"

ADMINS = [6302873072]  # adminlar IDlari

DB = "bot.db"
SESS_DIR = "sessions"
os.makedirs(SESS_DIR, exist_ok=True)    

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================= GLOBALS =================
import sqlite3
import datetime

# Admin tomonidan tasdiqlangan userlar (restart safe)
approved_users = set()

# Admin tasdiqlash so‘rovlari
# user_id -> [(admin_id, message_id)]
pending_requests = {}

# ▶️ Ishlayotgan yuborish tasklari
# user_id -> {session: asyncio.Task}
running_tasks = {}

# 🔐 Ishlayotgan Telethon clientlar
# user_id -> {session: TelegramClient}
running_clients = {}

# 🚫 Shadow-ban bo‘lgan sessionlar (restart safe)
shadow_banned = set()

# ================= TELETHON GLOBAL CACHE =================

# session -> TelegramClient (GLOBAL CACHE)
telethon_clients = {}

# session -> asyncio.Lock (1 session = 1 lock)
telethon_locks = {}

# session -> list[(group_id, title)]
groups_cache = {}


async def get_client(sess: str):
    if sess not in telethon_locks:
        telethon_locks[sess] = asyncio.Lock()

    async with telethon_locks[sess]:
        if sess in telethon_clients:
            return telethon_clients[sess], telethon_locks[sess]

        client = TelegramClient(
            f"{SESS_DIR}/{sess}",
            API_ID,
            API_HASH
        )

        await client.connect()

        if not await client.is_user_authorized():
            raise RuntimeError(f"Session {sess} avtorizatsiyadan o‘tmagan")

        telethon_clients[sess] = client
        return client, telethon_locks[sess]



# ================= DATABASE =================
# ================= DATABASE =================
DB = "bot.db"

def db():
    return sqlite3.connect(DB, timeout=30)

# DB yaratilishi va restartda ma'lumotlarni yuklash
with db() as c:

    # 📱 Raqamlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS numbers(
            user_id INTEGER,
            session TEXT
        )
    """)

    # 👥 Tanlangan guruhlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS selected_groups(
            user_id INTEGER,
            session TEXT,
            group_id INTEGER,
            title TEXT
        )
    """)

    # 📊 Statistika (YANGILANGAN)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stats(
            user_id INTEGER,
            session TEXT,
            group_id INTEGER,
            messages_sent INTEGER,
            last_sent TEXT
        )
    """)

    # 🔧 ESKI DB UCHUN FIX (Railway xatosini tuzatadi)
    try:
        c.execute("ALTER TABLE stats ADD COLUMN user_id INTEGER")
    except:
        pass

    # ✅ Tasdiqlangan userlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS approved_users(
            user_id INTEGER PRIMARY KEY
        )
    """)
    rows = c.execute("SELECT user_id FROM approved_users").fetchall()
    approved_users.update(r[0] for r in rows)

    # 🚫 Shadow-ban bo‘lgan sessionlar
    c.execute("""
        CREATE TABLE IF NOT EXISTS shadow_banned(
            session TEXT PRIMARY KEY
        )
    """)
    rows = c.execute("SELECT session FROM shadow_banned").fetchall()
    shadow_banned.update(r[0] for r in rows)


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
    kb.add("✉️ Habar yuborish", "⛔ Stop", "📊 Statistika")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# ================= ADMIN =================
from aiogram.utils.markdown import hlink

# ================= SOROV YUBORISH =================
@dp.callback_query_handler(lambda c: c.data.startswith("send_request:"))
async def send_request(call: types.CallbackQuery):
    uid = int(call.data.split(":")[1])

    # Agar foydalanuvchi allaqachon tasdiqlangan bo‘lsa
    if uid in approved_users:
        await call.answer("✅ Siz allaqachon tasdiqlangansiz.")
        return

    # Adminlarga xabar yuborish (avvalgi send_admin_request kabi)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{uid}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{uid}")
    )

    pending_requests[uid] = []

    user_profile_link = hlink(f"Foydalanuvchi: {uid}", f"tg://user?id={uid}")
    successful_admins = []

    for admin in ADMINS:
        try:
            msg_admin = await bot.send_message(
                admin,
                f"{user_profile_link}\n📩 Botga kirishga ruxsat so‘rayapti (to‘lov qilgan)",
                parse_mode="HTML",
                reply_markup=kb
            )
            pending_requests[uid].append((admin, msg_admin.message_id))
            successful_admins.append(str(admin))
        except Exception as e:
            print(f"❌ Adminga xabar yuborib bo‘lmadi ({admin}): {e}")

    if successful_admins:
        await call.message.answer("✅ Sorov adminlarga yuborildi. Iltimos javob kuting.")
    else:
        await call.message.answer("❌ Adminlarga sorov yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")

    await call.answer()



# ================= ADMIN DECISION =================
from aiogram import types

@dp.callback_query_handler(lambda c: c.data.startswith(("approve:", "reject:")))
async def admin_decision(call: types.CallbackQuery):
    """
    Admin sorovni tasdiqlash yoki rad etish tugmasi bosganda ishlaydi.
    Tasdiqlangan foydalanuvchilar DB-ga yoziladi,
    rad etilganlar esa faqat xabar oladi.
    """
    action, uid = call.data.split(":")
    uid = int(uid)

    if uid not in pending_requests:
        await call.answer("⛔ Allaqachon hal qilingan")
        return

    text = "✅ Tasdiqlandi" if action == "approve" else "❌ Rad etildi"

    # Admin xabarlarini tahrirlash
    for admin_id, msg_id in pending_requests[uid]:
        try:
            await bot.edit_message_text(text, admin_id, msg_id)
        except Exception:
            pass

    # Foydalanuvchiga natija yuborish
    if action == "approve":
        approved_users.add(uid)
        with db() as c:
            c.execute("INSERT OR IGNORE INTO approved_users(user_id) VALUES (?)", (uid,))
        await bot.send_message(uid, "✅ Siz tasdiqlandingiz. Botdan foydalanishingiz mumkin.")
    else:
        await bot.send_message(uid, "❌ Siz admin tomonidan rad etildingiz.")

    # Pending requestni tozalash
    del pending_requests[uid]

    # Callback tugmasini tasdiqlash
    await call.answer("✔️ Bajarildi")

# ================= START =================
# ================= START =================
@dp.message_handler(commands=["start"])
async def start(msg):
    uid = msg.from_user.id

    if uid in ADMINS or uid in approved_users:
        await main_menu(msg)
        return

    # 1️⃣ Foydalanuvchiga salomlashish va to‘lov haqida habar
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton(
            "💳 To‘lov qilish va admin bilan bog‘lanish",
            url="https://t.me/akramjonov0101"  # bu yerga admin username yozing
        )
    )
    await msg.answer(
        "👋 Salom!\nBotdan foydalanish uchun avval admin bilan bog‘lanib to‘lov qilishingiz kerak.",
        reply_markup=kb
    )

    # 2️⃣ Foydalanuvchi to‘lov qilgan bo‘lsa, sorov yuborish tugmasi
    kb2 = types.InlineKeyboardMarkup()
    kb2.add(types.InlineKeyboardButton("📩 Sorov yuborish", callback_data=f"send_request:{uid}"))
    await msg.answer(
        "To‘lov qilgan bo‘lsangiz, sorov yuborish tugmasini bosing:",
        reply_markup=kb2
    )


# =====================================================
# ================= 📱 RAQAMLAR (MULTI-USER SAFE + CODE RETRY) =======================
# =====================================================

import re
import asyncio
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

# ================= GLOBAL =================
# user_id -> {session: client}
login_clients = {}
# user_id -> {session: data}
login_data = {}
# session -> asyncio.Lock
session_locks = {}

# ================= SAFE DISCONNECT =================
async def safe_disconnect(user_id: int, session: str = None, state: FSMContext = None):
    """
    Xavfsiz tarzda clientni disconnect qiladi va login_data dan tozalaydi.
    Agar session berilsa faqat o'sha sessionni, aks holda barcha sessionlarni.
    """
    if user_id in login_clients:
        sessions_to_remove = [session] if session else list(login_clients[user_id].keys())
        for sess in sessions_to_remove:
            client = login_clients[user_id].pop(sess, None)
            login_data[user_id].pop(sess, None)
            lock = session_locks.pop(sess, None)
            if client:
                try: await client.disconnect()
                except: pass

        if not login_clients[user_id]:
            login_clients.pop(user_id)
            login_data.pop(user_id)

    if state:
        await state.finish()


# ================= BACK =================
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", state="*")
async def back_handler(msg: types.Message, state: FSMContext):
    await safe_disconnect(msg.from_user.id, state=state)
    await main_menu(msg)

# ================= MENU =================
@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar bo‘limi", reply_markup=kb)

# ================= ADD NUMBER =================
@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg: types.Message):
    uid = msg.from_user.id
    if uid in login_clients and login_clients[uid]:
        await msg.answer("⏳ Avvalgi ulanish tugashini kuting")
        return

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📱 Raqamni ulashish", request_contact=True))
    kb.add("⬅️ Orqaga")

    await msg.answer("📞 Telefon raqamni kiriting (+998...)", reply_markup=kb)
    await AddNum.phone.set()

# ================= PHONE =================
@dp.message_handler(state=AddNum.phone, content_types=["text", "contact"])
async def get_phone(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    phone = msg.contact.phone_number if msg.contact else msg.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    session = phone.replace("+", "")
    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH, timeout=20)
    lock = asyncio.Lock()
    session_locks[session] = lock

    try:
        await client.connect()
        sent = await asyncio.wait_for(client.send_code_request(phone), timeout=30)

        if uid not in login_clients:
            login_clients[uid] = {}
            login_data[uid] = {}

        login_clients[uid][session] = client
        login_data[uid][session] = {
            "phone": phone,
            "session": session,
            "hash": sent.phone_code_hash
        }

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("🔁 Kodni qayta yuborish", "⬅️ Orqaga")

        await AddNum.code.set()
        await msg.answer("📨 SMS kodni kiriting:", reply_markup=kb)

    except Exception as e:
        await msg.answer(f"❌ Kod yuborilmadi:\n{e}")
        await safe_disconnect(uid, session, state)

# ================= CODE =================
@dp.message_handler(state=AddNum.code)
async def get_code(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    user_sessions = login_data.get(uid, {})
    if not user_sessions:
        await msg.answer("❌ Sessiya topilmadi")
        return await safe_disconnect(uid, state=state)

    # Hozirgi session (faqat 1 ta ulanish)
    session, data = list(user_sessions.items())[0]
    client = login_clients[uid][session]
    lock = session_locks.get(session)

    if msg.text == "🔁 Kodni qayta yuborish":
        try:
            async with lock:
                sent = await client.send_code_request(data["phone"])
            data["hash"] = sent.phone_code_hash
            await msg.answer("🔁 Yangi kod yuborildi")
        except Exception as e:
            await msg.answer(f"❌ Qayta yuborib bo‘lmadi:\n{e}")
        return

    code = re.sub(r"\D", "", msg.text)

    try:
        async with lock:
            await client.sign_in(
                phone=data["phone"],
                code=code,
                phone_code_hash=data["hash"]
            )

    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2FA parolni kiriting:")
        return

    except Exception as e:
        await msg.answer(f"❌ Kod xato:\n{e}")
        return  # Qayta urinishi mumkin, state hali tugamadi

    # DB ga saqlash
    with db() as c:
        c.execute(
            "INSERT INTO numbers (user_id, session) VALUES (?,?)",
            (uid, data["session"])
        )

    await msg.answer("✅ Session muvaffaqiyatli qo‘shildi")
    await safe_disconnect(uid, session, state)
    await numbers_menu(msg)

# ================= PASSWORD =================
@dp.message_handler(state=AddNum.password)
async def get_password(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    user_sessions = login_data.get(uid, {})
    if not user_sessions:
        await msg.answer("❌ Sessiya topilmadi")
        return await safe_disconnect(uid, state=state)

    session, data = list(user_sessions.items())[0]
    client = login_clients[uid][session]
    lock = session_locks.get(session)

    try:
        async with lock:
            await client.sign_in(password=msg.text.strip())

        with db() as c:
            c.execute(
                "INSERT INTO numbers (user_id, session) VALUES (?,?)",
                (uid, data["session"])
            )

        await msg.answer("✅ Session qo‘shildi (2FA)")

    except Exception as e:
        await msg.answer(f"❌ Parol xato:\n{e}")
        return  # Qayta urinishi mumkin

    await safe_disconnect(uid, session, state)
    await numbers_menu(msg)


# ================= SESSION O‘CHIRISH =================
@dp.message_handler(lambda m: m.text == "🗑 Raqam o‘chirish")
async def delete_session(msg: types.Message):
    uid = msg.from_user.id
    with db() as c:
        rows = c.execute(
            "SELECT session FROM numbers WHERE user_id=?", (uid,)
        ).fetchall()

    if not rows:
        await msg.answer("❌ Sessionlar mavjud emas")
        return

    kb = types.InlineKeyboardMarkup()
    for (sess,) in rows:
        kb.add(types.InlineKeyboardButton(
            f"❌ {sess}",
            callback_data=f"delsess:{sess}"
        ))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="back"))
    await msg.answer("🗑 O‘chiriladigan sessionni tanlang", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith("delsess:"))
async def confirm_delete(call: types.CallbackQuery):
    sess = call.data.split(":")[1]
    uid = call.from_user.id

    # Taskni to‘xtatish (multi-session safe)
    task = running_tasks.get(uid, {}).pop(sess, None)
    if task:
        task.cancel()

    # Clientni xavfsiz uzish
    client = running_clients.get(uid, {}).pop(sess, None)
    if client:
        try:
            await client.disconnect()
        except: pass

    # DB dan o‘chirish
    with db() as c:
        c.execute("DELETE FROM numbers WHERE session=?", (sess,))
        c.execute("DELETE FROM selected_groups WHERE session=?", (sess,))
        c.execute("DELETE FROM stats WHERE session=?", (sess,))

    # Session faylini o‘chirish
    try:
        os.remove(f"{SESS_DIR}/{sess}.session")
    except: pass

    groups_cache.pop(sess, None)
    telethon_clients.pop(sess, None)
    telethon_locks.pop(sess, None)


    await call.message.edit_text("✅ Session o‘chirildi")



# ================= GURUHLAR BO‘LIMI =================
GROUPS_PER_PAGE = 25

@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups_menu(msg: types.Message):
    uid = msg.from_user.id
    with db() as c:
        sessions = c.execute(
            "SELECT session FROM numbers WHERE user_id=?", (uid,)
        ).fetchall()

    if not sessions:
        await msg.answer("❌ Avval akkaunt qo‘shing")
        return

    kb = types.InlineKeyboardMarkup()
    for (sess,) in sessions:
        kb.add(types.InlineKeyboardButton(
            f"📱 {sess}",
            callback_data=f"grp_menu:{sess}"
        ))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="grp_back"))

    await msg.answer("📂 Session tanlang:", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("grp_menu:"))
async def grp_session_menu(call: types.CallbackQuery):
    sess = call.data.split(":")[1]

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("➕ Guruh qo‘shish", callback_data=f"grp_all:{sess}:0"))
    kb.add(types.InlineKeyboardButton("✅ Tanlangan guruhlar", callback_data=f"grp_sel:{sess}:0"))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="grp_back"))

    from aiogram.utils.exceptions import MessageNotModified

    try:
        await call.message.edit_text(f"📱 Session: {sess}", reply_markup=kb)
    except MessageNotModified:
        pass

    await call.answer()


# ================= BARCHA GURUHLARNI OLISH (SAFE) =================
async def fetch_all_groups(sess: str):
    if sess in groups_cache:
        return groups_cache[sess]

    client, lock = await get_client(sess)
    async with lock:
        dialogs = []
        async for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                dialogs.append((d.id, d.name or "No name"))

    groups_cache[sess] = dialogs
    return dialogs



# ================= GURUH QO‘SHISH (PAGINATION + SAFE) =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_all:"))
async def grp_all(call: types.CallbackQuery):
    parts = call.data.split(":")
    sess = parts[1]
    page = int(parts[2])
    uid = call.from_user.id

    all_groups = await fetch_all_groups(sess)
    # DB dan tanlangan guruhlarni olamiz
    uid = call.from_user.id
    with db() as c:
        selected_ids = {r[0] for r in c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (uid, sess)
        )}

    groups = [g for g in all_groups if g[0] not in selected_ids]

    start = page * GROUPS_PER_PAGE
    end = start + GROUPS_PER_PAGE

    kb = types.InlineKeyboardMarkup()
    for gid, title in groups[start:end]:
        kb.add(types.InlineKeyboardButton(title[:30], callback_data=f"grp_add:{sess}:{gid}:{page}"))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"grp_all:{sess}:{page-1}"))
    if end < len(groups):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"grp_all:{sess}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"grp_menu:{sess}"))

    from aiogram.utils.exceptions import MessageNotModified

    # Safe edit
    try:
        await call.message.edit_text("➕ Guruh qo‘shish:", reply_markup=kb)
    except MessageNotModified:
        pass

    await call.answer()




# ================= GURUHNI TANLASH (SAFE) =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_add:"))
async def grp_add(call: types.CallbackQuery):
    parts = call.data.split(":")
    sess = parts[1]
    gid = int(parts[2])
    page = int(parts[3])
    uid = call.from_user.id

    # TelegramClient bilan guruh nomini olish
    client, lock = await get_client(sess)
    async with lock:
        ent = await client.get_entity(gid)
        title = (ent.title or "No name")[:30]

    # DB ga yozish
    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO selected_groups (user_id, session, group_id, title) VALUES (?,?,?,?)",
            (uid, sess, gid, title)
        )

    await call.answer("✅ Tanlandi")

    # 🔥 MUHIM: Bu qatorni o‘chiramiz
    # await call.message.edit_reply_markup(reply_markup=call.message.reply_markup)

    # Keyingi sahifani ko‘rsatish
    @dp.callback_query_handler(lambda c: c.data.startswith("grp_add:"))
    async def grp_add(call: types.CallbackQuery):
        parts = call.data.split(":")
        sess = parts[1]
        gid = int(parts[2])
        page = int(parts[3])
        uid = call.from_user.id  # endi bu hech qachon None bo‘lmaydi

        # TelegramClient bilan guruh nomini olish
        client, lock = await get_client(sess)
        async with lock:
            ent = await client.get_entity(gid)
            title = (ent.title or "No name")[:30]

        # DB ga yozish
        with db() as c:
            c.execute(
                "INSERT OR IGNORE INTO selected_groups (user_id, session, group_id, title) VALUES (?,?,?,?)",
                (uid, sess, gid, title)
            )

        # Foydalanuvchiga xabar
        await call.answer("✅ Tanlandi")

        # Tugmalarni yangilash (eski callback tugmalarini olib tashlash)
        await call.message.edit_reply_markup()







# ================= TANLANGAN GURUHLAR =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_sel:"))
async def grp_selected(call: types.CallbackQuery):
    _, sess, page = call.data.split(":")
    page = int(page)
    uid = call.from_user.id

    with db() as c:
        rows = c.execute(
            "SELECT group_id, title FROM selected_groups WHERE user_id=? AND session=?",
            (uid, sess)
        ).fetchall()

    start = page * GROUPS_PER_PAGE
    end = start + GROUPS_PER_PAGE

    kb = types.InlineKeyboardMarkup()
    for gid, title in rows[start:end]:
        kb.add(types.InlineKeyboardButton(
            f"❌ {title}",
            callback_data=f"grp_remove:{sess}:{gid}:{page}"
        ))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"grp_sel:{sess}:{page-1}"))
    if end < len(rows):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"grp_sel:{sess}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"grp_menu:{sess}"))

    await call.message.edit_text("✅ Tanlangan guruhlar:", reply_markup=kb)
    await call.answer()


# ================= TANLANGANDAN O‘CHIRISH =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_remove:"))
async def grp_remove(call: types.CallbackQuery):
    _, sess, gid, page = call.data.split(":")
    gid = int(gid)
    uid = call.from_user.id

    with db() as c:
        c.execute(
            "DELETE FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
            (uid, sess, gid)
        )

    await call.answer("❌ O‘chirildi")
    await grp_selected(call)


# ================= ORQAGA =================
@dp.callback_query_handler(lambda c: c.data == "grp_back")
async def grp_back(call: types.CallbackQuery):
    await main_menu(call.message)
    await call.answer()

# =====================================================
# ================= ✉️ HABAR YUBORISH =================
# =====================================================

async def send_loop(user_id: int, session: str, text: str, groups: list, interval: int):
    """
    Smart spam control bilan xabar yuborish loopi
    - flood/shadow-ban avtomatik tekshiradi
    - spamga yaqinlashsa kutadi
    - intervalda yuborishni davom ettiradi
    """
    client, lock = await get_client(session)
    if user_id not in running_clients:
        running_clients[user_id] = {}
    running_clients[user_id][session] = client

    if user_id not in running_tasks:
        running_tasks[user_id] = {}

    async def loop():
        flood_count = 0
        while True:
            for (gid,) in groups:
                # Agar session shadow-ban yoki spam xavfi bo‘lsa kutish
                if session in shadow_banned:
                    await bot.send_message(user_id, f"⚠️ {session} shadow-ban bo‘lgan. To‘xtatildi.")
                    return

                try:
                    async with lock:
                        await client.send_message(gid, text)

                    # Statistika yozish
                    with db() as c:
                        c.execute("""
                            INSERT OR REPLACE INTO stats(user_id, session, group_id, messages_sent, last_sent)
                            VALUES(?, ?, ?, COALESCE((SELECT messages_sent FROM stats WHERE user_id=? AND session=? AND group_id=?) + 1, 1), ?)
                        """, (user_id, session, gid, user_id, session, gid, datetime.datetime.now().isoformat()))

                    # Normal interval kutish
                    await asyncio.sleep(interval * 60)

                except FloodWaitError as e:
                    # Flood xatolik: avtomatik kutish
                    flood_count += 1
                    wait_time = e.seconds + 30  # qo‘shimcha 30 sekund kutish
                    await bot.send_message(user_id, f"⚠️ Flood xavfi: {session} {wait_time}s kutiladi.")
                    await asyncio.sleep(wait_time)
                    if flood_count >= 3:
                        shadow_banned.add(session)
                        with db() as c:
                            c.execute("INSERT OR IGNORE INTO shadow_banned(session) VALUES (?)", (session,))
                        await bot.send_message(user_id, f"⚠️ {session} flood sababli avtomatik to‘xtatildi.")
                        return

                except UserIsBlockedError:
                    shadow_banned.add(session)
                    with db() as c:
                        c.execute("INSERT OR IGNORE INTO shadow_banned(session) VALUES (?)", (session,))
                    await bot.send_message(user_id, f"⛔ {session} bloklandi. Task to‘xtatildi.")
                    return

                except Exception as e:
                    if "invalid peer" in str(e).lower():
                        logging.error(f"[INVALID PEER] {session} -> {gid}")
                        continue

                    logging.error(f"[SEND ERROR] {session} -> {gid}: {e}")
                    await asyncio.sleep(20)


            # Agar interval juda qisqa va spam xavfi yuqori bo‘lsa, avtomatik kutish
            await asyncio.sleep(interval * 60)

    running_tasks[user_id][session] = asyncio.create_task(loop())


# ================= START SEND FLOW =================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg: types.Message):
    uid = msg.from_user.id
    with db() as c:
        sessions = c.execute("SELECT session FROM numbers WHERE user_id=?", (uid,)).fetchall()

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
async def send_get_text(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return

    await state.update_data(session=msg.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Orqaga")
    await msg.answer("✏️ Habar matnini kiriting:", reply_markup=kb)
    await SendFlow.text.set()


@dp.message_handler(state=SendFlow.text)
async def send_choose_interval(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return

    await state.update_data(text=msg.text)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⏱ 5", "⏱ 10", "⏱ 15", "⏱ 20")
    kb.add("⬅️ Orqaga")
    await msg.answer("⏱ Intervalni tanlang (daqiqada):", reply_markup=kb)
    await SendFlow.interval.set()


@dp.message_handler(state=SendFlow.interval)
async def start_sending(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await main_menu(msg)
        return

    try:
        interval = int(msg.text.replace("⏱", "").strip())
    except ValueError:
        await msg.answer("❌ Noto‘g‘ri interval")
        return

    data = await state.get_data()
    session = data["session"]
    text = data["text"]
    user_id = msg.from_user.id

    # Guruhlarni olish
    with db() as c:
        groups = c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (user_id, session)
        ).fetchall()

    if not groups:
        await msg.answer("❌ Guruh tanlanmagan")
        return

    # Taskni ishga tushurish
    await send_loop(user_id, session, text, groups, interval)
    await state.finish()
    await msg.answer("▶️ Yuborish boshlandi")
    await main_menu(msg)



# ================= STOP =================
@dp.message_handler(lambda m: m.text == "⛔ Stop")
async def stop_all(msg: types.Message):
    user_id = msg.from_user.id

    # Barcha ishlayotgan tasklarni to‘xtatish
    tasks = running_tasks.pop(user_id, {})
    for task in tasks.values():
        task.cancel()

    # Barcha clientlarni uzish
    clients = running_clients.pop(user_id, {})
    for client in clients.values():
        try:
            await client.disconnect()
        except:
            pass

    await msg.answer("⛔ To‘xtatildi")
    await main_menu(msg)


# ================= STATISTIKA =================
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def show_stats(msg):
    with db() as c:
        rows = c.execute("SELECT session, group_id, messages_sent, last_sent FROM stats").fetchall()
    text = "📊 Statistika:\n\n"
    for row in rows:
        text += f"Session: {row[0]}\nGuruh: {row[1]}\nXabarlar: {row[2]}\nOxirgi yuborish: {row[3]}\n\n"
    await msg.answer(text or "📊 Statistika mavjud emas.")

# ================= RUN =================
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
