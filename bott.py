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

ADMINS = [6302873072, 6731395876]  # adminlar IDlari

DB = "bot.db"
SESS_DIR = "sessions"
os.makedirs(SESS_DIR, exist_ok=True)    

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

# ================= GLOBALS =================

# Admin tomonidan tasdiqlangan userlar
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

# 🚫 Shadow-ban bo‘lgan sessionlar
shadow_banned = set()

# ================= TELETHON GLOBAL CACHE =================

# session -> TelegramClient (GLOBAL CACHE)
telethon_clients = {}

# session -> asyncio.Lock (1 session = 1 lock)
telethon_locks = {}


async def get_client(sess: str):
    if sess not in telethon_clients:
        client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
        await client.start()
        telethon_clients[sess] = client
        telethon_locks[sess] = asyncio.Lock()
    return telethon_clients[sess], telethon_locks[sess]


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
    c.execute("""CREATE TABLE IF NOT EXISTS stats(
        session TEXT,
        group_id INTEGER,
        messages_sent INTEGER,
        last_sent TEXT
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
    kb.add("✉️ Habar yuborish", "⛔ Stop", "📊 Statistika")
    await msg.answer("🏠 Asosiy menyu", reply_markup=kb)

# ================= ADMIN =================
from aiogram.utils.markdown import hlink

async def send_admin_request(user_id: int):
    """
    Foydalanuvchi botga kirishni so'raganda adminlarga xabar yuboradi
    va foydalanuvchiga tasdiqlash yuborilganini bildiradi.
    Bosilganda profil ochiladi.
    """
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{user_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{user_id}")
    )

    pending_requests[user_id] = []
    successful_admins = []

    # 🔗 Bosiladigan profil linki
    user_profile_link = hlink(f"Foydalanuvchi: {user_id}", f"tg://user?id={user_id}")

    for admin in ADMINS:
        try:
            msg = await bot.send_message(
                admin,
                f"{user_profile_link}\n📩 Botga kirishga ruxsat so‘rayapti",
                parse_mode="HTML",
                reply_markup=kb
            )
            pending_requests[user_id].append((admin, msg.message_id))
            successful_admins.append(str(admin))
        except Exception as e:
            print(f"❌ Adminga xabar yuborib bo‘lmadi ({admin}): {e}")

    if successful_admins:
        await bot.send_message(user_id, "✅ So‘rovingiz adminlarga yuborildi.")
    else:
        await bot.send_message(user_id, "❌ Adminlarga so‘rov yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")



@dp.callback_query_handler(lambda c: c.data.startswith(("approve:", "reject:")))
async def admin_decision(call: types.CallbackQuery):
    """
    Admin sorovni tasdiqlash yoki rad etish tugmasini bosganda ishlaydi.
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
        await bot.send_message(uid, "✅ Siz tasdiqlandingiz. Botdan foydalanishingiz mumkin.")
    else:
        await bot.send_message(uid, "❌ Siz admin tomonidan rad etildingiz.")

    # Pending requestni tozalash
    del pending_requests[uid]

    # Callback tugmasini tasdiqlash
    await call.answer("✔️ Bajarildi")

# ================= START =================
@dp.message_handler(commands=["start"])
async def start(msg):
    uid = msg.from_user.id
    if uid in ADMINS or uid in approved_users: await main_menu(msg)
    else:
        await send_admin_request(uid)
        await msg.answer("⏳ Adminlar tasdiqlashini kuting...")


import re
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
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

# ================= STATES =================
class AddNum(StatesGroup):
    phone = State()
    code = State()
    password = State()

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

    await call.message.edit_text("✅ Session o‘chirildi")



# ==================== GURUH QO‘SHISH / TANLASH / PAGINATION ====================

GROUPS_PER_PAGE = 25

# Barcha guruhlarni olish (Telethon safe)
async def fetch_all_groups(sess: str):
    client, lock = await get_client(sess)
    async with lock:
        dialogs = []
        async for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                dialogs.append((d.id, d.name or "No name"))
        return dialogs

# Guruhlarni ko'rsatish (pagination)
async def grp_all(call: types.CallbackQuery, page: int = 0, answer_called=False):
    parts = call.data.split(":")
    sess = parts[1]

    uid = call.from_user.id
    all_groups = await fetch_all_groups(sess)

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
        kb.add(types.InlineKeyboardButton(
            title[:30],
            callback_data=f"grp_add:{sess}:{gid}:{page}"
        ))

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️", callback_data=f"grp_all:{sess}:{page-1}"))
    if end < len(groups):
        nav.append(types.InlineKeyboardButton("➡️", callback_data=f"grp_all:{sess}:{page+1}"))
    if nav:
        kb.row(*nav)

    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=f"grp_menu:{sess}"))

    await call.message.edit_text("➕ Guruh qo‘shish:", reply_markup=kb)
    if not answer_called:
        await call.answer()

# Callback: guruh qo‘shish
@dp.callback_query_handler(lambda c: c.data.startswith("grp_add:"))
async def grp_add(call: types.CallbackQuery):
    parts = call.data.split(":")
    sess = parts[1]
    gid = int(parts[2])
    page = int(parts[3])
    uid = call.from_user.id

    client, lock = await get_client(sess)
    async with lock:
        ent = await client.get_entity(gid)
        title = (ent.title or "No name")[:30]

    with db() as c:
        c.execute(
            "INSERT OR IGNORE INTO selected_groups (user_id, session, group_id, title) VALUES (?,?,?,?)",
            (uid, sess, gid, title)
        )

    # Faqat bitta call.answer
    await call.answer("✅ Tanlandi", show_alert=False)

    # Yangi page bilan callback chaqirish, answer_called=True
    call.data = f"grp_all:{sess}:{page}"
    await grp_all(call, page=page, answer_called=True)

# Callback: tanlangan guruhlar
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

# Callback: tanlangan guruhni o‘chirish
@dp.callback_query_handler(lambda c: c.data.startswith("grp_remove:"))
async def grp_remove(call: types.CallbackQuery):
    _, sess, gid, page = call.data.split(":")
    gid = int(gid)
    page = int(page)
    uid = call.from_user.id

    with db() as c:
        c.execute(
            "DELETE FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
            (uid, sess, gid)
        )

    await call.answer("❌ O‘chirildi", show_alert=False)

    # Tanlangan guruhlar menuni yangilash
    call.data = f"grp_sel:{sess}:{page}"
    await grp_selected(call)

# Callback: session menuga qaytish
@dp.callback_query_handler(lambda c: c.data == "grp_back")
async def grp_back(call: types.CallbackQuery):
    await main_menu(call.message)
    await call.answer()

# =====================================================
# ================= ✉️ HABAR YUBORISH =================
# =====================================================

# Send loop: multi-user safe, shadow-ban check, statistikani yozadi
async def send_loop(user_id: int, session: str, text: str, groups: list, interval: int):
    client, lock = await get_client(session)

    if user_id not in running_clients:
        running_clients[user_id] = {}
    running_clients[user_id][session] = client

    async def loop():
        try:
            while True:
                for (gid,) in groups:

                    if session in shadow_banned:
                        await bot.send_message(user_id, f"⚠️ {session} shadow-ban bo‘lgan. To‘xtatildi.")
                        running_tasks.get(user_id, {}).pop(session, None)
                        return

                    try:
                        async with lock:
                            await client.send_message(gid, text)

                        # Statistika
                        with db() as c:
                            c.execute("""
                                INSERT OR REPLACE INTO stats(session, group_id, messages_sent, last_sent)
                                VALUES(?, ?, COALESCE((SELECT messages_sent FROM stats WHERE session=? AND group_id=?) + 1, 1), ?)
                            """, (session, gid, session, gid, datetime.datetime.now().isoformat()))

                        # Guruhlar orasida random delay
                        await asyncio.sleep(random.randint(15, 30))

                    except FloodWaitError as e:
                        await asyncio.sleep(e.seconds + 5)
                    except UserIsBlockedError:
                        shadow_banned.add(session)
                        await bot.send_message(user_id, f"⛔ {session} bloklandi. Task to‘xtatildi.")
                        running_tasks.get(user_id, {}).pop(session, None)
                        return
                    except Exception as e:
                        logging.error(f"[SEND ERROR] {session} -> {gid}: {e}")

                await asyncio.sleep(interval * 60)

        except asyncio.CancelledError:
            logging.info(f"[STOPPED] user={user_id} session={session}")
            return

    if user_id not in running_tasks:
        running_tasks[user_id] = {}
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
