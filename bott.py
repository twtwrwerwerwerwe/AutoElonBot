# =====================================================
# MULTI SESSION TELEGRAM BOT (ULTIMATE FULL - ANTI-FLOOD + SHADOW BAN + MULTI CLIENT)
# Aiogram 2.25.1 + Telethon
# =====================================================

import os, asyncio, sqlite3, random, datetime
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError, UserIsBlockedError

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
approved_users = set()
pending_requests = {}      # user_id -> [(admin_id, msg_id)]
running_tasks = {}
running_clients = {}
shadow_banned = set()

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
# ================= ADMIN REQUEST =================
async def send_admin_request(user_id: int):
    """
    Foydalanuvchi botga kirishni so'raganda adminlarga xabar yuboradi
    va foydalanuvchiga tasdiqlash yuborilganini bildiradi.
    """
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"approve:{user_id}"),
        types.InlineKeyboardButton("❌ Rad etish", callback_data=f"reject:{user_id}")
    )

    pending_requests[user_id] = []
    successful_admins = []

    for admin in ADMINS:
        try:
            msg = await bot.send_message(
                admin,
                f"👤 Foydalanuvchi <a href='tg://user?id={user_id}'>{user_id}</a> botga kirishni so‘rayapti",
                parse_mode="HTML",
                reply_markup=kb
            )
            pending_requests[user_id].append((admin, msg.message_id))
            successful_admins.append(str(admin))
        except Exception as e:
            print(f"❌ Adminga xabar yuborib bo‘lmadi ({admin}): {e}")

    if successful_admins:
        await bot.send_message(user_id, f"✅ Sorov adminlarga yuborildi: {', '.join(successful_admins)}")
    else:
        await bot.send_message(user_id, "❌ Adminlarga sorov yuborib bo‘lmadi. Keyinroq urinib ko‘ring.")


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

login_clients = {}
login_data = {}

# =====================================================
# ================= 📱 RAQAMLAR =======================
# =====================================================

login_clients = {}
login_data = {}

# 🔙 UNIVERSAL BACK (TO‘G‘RILANDI)
@dp.message_handler(lambda m: m.text == "⬅️ Orqaga", state="*")
async def back_handler(msg: types.Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state is None:
        # 📱 Raqamlar bo‘limidan → ASOSIY MENYU
        await main_menu(msg)
    else:
        # 📞 Raqam qo‘shish / kod / parol ichidan → RAQAMLAR
        await state.finish()
        await numbers_menu(msg)


@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("⬅️ Orqaga")
    await msg.answer("📱 Raqamlar bo‘limi", reply_markup=kb)


@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("📱 Raqamni ulashish", request_contact=True))
    kb.add("⬅️ Orqaga")
    await msg.answer("📞 Telefon raqam kiriting (+998...)", reply_markup=kb)
    await AddNum.phone.set()


# ================= PHONE =================
@dp.message_handler(state=AddNum.phone, content_types=["text", "contact"])
async def get_phone(msg: types.Message, state: FSMContext):
    phone = msg.contact.phone_number if msg.contact else msg.text.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    session = phone.replace("+", "")
    client = TelegramClient(f"{SESS_DIR}/{session}", API_ID, API_HASH)
    await client.connect()

    try:
        sent = await client.send_code_request(phone)

        login_clients[msg.from_user.id] = client
        login_data[msg.from_user.id] = {
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
        await client.disconnect()
        await state.finish()


# ================= CODE =================
@dp.message_handler(state=AddNum.code)
async def get_code(msg: types.Message, state: FSMContext):
    data = login_data.get(msg.from_user.id)
    client = login_clients.get(msg.from_user.id)

    if not data or not client:
        await msg.answer("❌ Sessiya yo‘q")
        await state.finish()
        return

    if msg.text == "🔁 Kodni qayta yuborish":
        sent = await client.send_code_request(data["phone"])
        data["hash"] = sent.phone_code_hash
        await msg.answer("🔁 Yangi kod yuborildi")
        return

    code = re.sub(r"\D", "", msg.text)

    try:
        await client.sign_in(
            phone=data["phone"],
            code=code,
            phone_code_hash=data["hash"]
        )

    except SessionPasswordNeededError:
        await AddNum.password.set()
        await msg.answer("🔐 2-bosqichli parolni kiriting:")
        return

    except Exception as e:
        await msg.answer(f"❌ Kod xato:\n{e}")
        await state.finish()
        return

    with db() as c:
        c.execute(
            "INSERT INTO numbers (user_id, session) VALUES (?, ?)",
            (msg.from_user.id, data["session"])
        )

    await msg.answer("✅ Profil qo‘shildi")
    await state.finish()
    await numbers_menu(msg)


# ================= PASSWORD =================
@dp.message_handler(state=AddNum.password)
async def get_password(msg: types.Message, state: FSMContext):
    data = login_data.get(msg.from_user.id)
    client = login_clients.get(msg.from_user.id)

    try:
        await client.sign_in(password=msg.text.strip())

        with db() as c:
            c.execute(
                "INSERT INTO numbers (user_id, session) VALUES (?, ?)",
                (msg.from_user.id, data["session"])
            )

        await msg.answer("✅ Profil qo‘shildi (2FA)")

    except Exception as e:
        await msg.answer(f"❌ Parol xato:\n{e}")
        return

    finally:
        await client.disconnect()
        login_clients.pop(msg.from_user.id, None)
        login_data.pop(msg.from_user.id, None)
        await state.finish()
        await numbers_menu(msg)

# ================= SESSION O‘CHIRISH =================

@dp.message_handler(lambda m: m.text == "🗑 Raqam o‘chirish")
async def delete_session(msg: types.Message):
    with db() as c:
        rows = c.execute(
            "SELECT session FROM numbers WHERE user_id=?",
            (msg.from_user.id,)
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

    if call.from_user.id in running_tasks:
        running_tasks[call.from_user.id].cancel()

    if call.from_user.id in running_clients:
        await running_clients[call.from_user.id].disconnect()

    with db() as c:
        c.execute("DELETE FROM numbers WHERE session=?", (sess,))
        c.execute("DELETE FROM selected_groups WHERE session=?", (sess,))
        c.execute("DELETE FROM stats WHERE session=?", (sess,))

    try:
        os.remove(f"{SESS_DIR}/{sess}.session")
    except:
        pass

    await call.message.edit_text("✅ Session o‘chirildi")


# =====================================================
# Keyingi qism: Guruhlar, Tanlangan guruhlar, Habar yuborish va Statistika
# =====================================================
# =====================================================
# ================= 👥 GURUHLAR =======================
# =====================================================

GROUPS_PER_PAGE = 30  # Har sahifada 30 ta guruh

# ================= GURUHLAR MENYU =================
@dp.message_handler(lambda m: m.text == "👥 Guruhlar")
async def groups_menu(msg: types.Message):
    with db() as c:
        sessions = c.execute(
            "SELECT session FROM numbers WHERE user_id=?",
            (msg.from_user.id,)
        ).fetchall()

    if not sessions:
        await msg.answer("❌ Avval akkaunt qo‘shing")
        return

    kb = types.InlineKeyboardMarkup(row_width=1)
    for (sess,) in sessions:
        kb.add(types.InlineKeyboardButton(
            f"📱 {sess}",
            callback_data=f"grp_sess:{sess}:0"
        ))
    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="grp_back"))

    await msg.answer("📂 Akkaunt tanlang:", reply_markup=kb)


# ================= GURUHLARNI SAHIFALASH =================
async def load_groups_page(call: types.CallbackQuery, sess: str, page: int):
    await call.answer("⏳ Guruhlar yuklanmoqda...")

    await call.message.edit_text("⏳ Guruhlar yuklanmoqda...")

    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
    await client.connect()

    # Tanlangan guruhlar
    with db() as c:
        selected = {row[0] for row in c.execute(
            "SELECT group_id FROM selected_groups WHERE user_id=? AND session=?",
            (call.from_user.id, sess)
        )}

    kb = types.InlineKeyboardMarkup(row_width=1)

    start = page * GROUPS_PER_PAGE
    end = start + GROUPS_PER_PAGE
    count = 0

    async for d in client.iter_dialogs():
        if not (d.is_group or d.is_channel):
            continue
        if count < start:
            count += 1
            continue
        if count >= end:
            break
        mark = "✅ " if d.id in selected else ""
        title = (d.name or "No name")[:30]
        kb.add(types.InlineKeyboardButton(
            f"{mark}{title}",
            callback_data=f"grp_toggle:{sess}:{d.id}:{page}"
        ))
        count += 1

    # Sahifa tugmalari
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton(
            "⬅️ Oldingi", callback_data=f"grp_page:{sess}:{page-1}"
        ))
    # Agar keyingi sahifa mavjud bo‘lsa
    if count >= end:
        nav_buttons.append(types.InlineKeyboardButton(
            "➡️ Keyingi", callback_data=f"grp_page:{sess}:{page+1}"
        ))
    if nav_buttons:
        kb.row(*nav_buttons)

    kb.add(types.InlineKeyboardButton("⬅️ Orqaga", callback_data="grp_back"))

    await call.message.edit_text("👥 Guruhlar ro‘yxati:", reply_markup=kb)
    await client.disconnect()


# ================= CALLBACK: SAHIFA =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_sess:"))
async def load_groups(call: types.CallbackQuery):
    _, sess, page = call.data.split(":")
    await load_groups_page(call, sess, int(page))


@dp.callback_query_handler(lambda c: c.data.startswith("grp_page:"))
async def change_page(call: types.CallbackQuery):
    _, sess, page = call.data.split(":")
    await load_groups_page(call, sess, int(page))


# ================= TOGGLE GROUP =================
@dp.callback_query_handler(lambda c: c.data.startswith("grp_toggle:"))
async def toggle_group(call: types.CallbackQuery):
    _, sess, gid, page = call.data.split(":")
    gid = int(gid)
    page = int(page)
    user_id = call.from_user.id

    with db() as c:
        exists = c.execute(
            "SELECT 1 FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
            (user_id, sess, gid)
        ).fetchone()

    client = TelegramClient(f"{SESS_DIR}/{sess}", API_ID, API_HASH)
    await client.connect()
    entity = await client.get_entity(gid)
    title = entity.title[:30]
    await client.disconnect()

    if exists:
        with db() as c:
            c.execute(
                "DELETE FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
                (user_id, sess, gid)
            )
        prefix = ""
        await call.answer("❌ Guruh olib tashlandi")
    else:
        with db() as c:
            c.execute(
                "INSERT INTO selected_groups (user_id, session, group_id, title) VALUES (?,?,?,?)",
                (user_id, sess, gid, title)
            )
        prefix = "✅ "
        await call.answer("✅ Guruh tanlandi")

    # Inline tugmani yangilash
    kb = call.message.reply_markup
    for row in kb.inline_keyboard:
        btn = row[0]
        if btn.callback_data.startswith(f"grp_toggle:{sess}:{gid}:"):
            btn.text = prefix + title

    await call.message.edit_reply_markup(reply_markup=kb)


# ================= BACK =================
@dp.callback_query_handler(lambda c: c.data == "grp_back")
async def grp_back(call: types.CallbackQuery):
    await main_menu(call.message)
    await call.answer()



# =====================================================
# ================= ✉️ HABAR YUBORISH =================
# =====================================================
@dp.message_handler(lambda m: m.text == "✉️ Habar yuborish")
async def send_start(msg):
    with db() as c:
        sessions = c.execute("SELECT session FROM numbers WHERE user_id=?", (msg.from_user.id,)).fetchall()
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
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Orqaga")
    await msg.answer("✏️ Habar matnini kiriting:", reply_markup=kb)
    await SendFlow.text.set()

@dp.message_handler(state=SendFlow.text)
async def send_choose_interval(msg, state):
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
                if session in shadow_banned:
                    await bot.send_message(user_id, "⚠️ Session shadow-banned! To‘xtatildi.")
                    running_tasks.pop(user_id, None)
                    return
                try:
                    await client.send_message(gid, text)
                    with db() as c:
                        c.execute(
                            "INSERT OR REPLACE INTO stats(session, group_id, messages_sent, last_sent) VALUES(?,?,COALESCE((SELECT messages_sent FROM stats WHERE session=? AND group_id=?)+1,1),?)",
                            (session, gid, session, gid, datetime.datetime.now().isoformat())
                        )
                    await asyncio.sleep(random.randint(15, 30))
                except FloodWaitError as e:
                    await asyncio.sleep(e.seconds + 5)
                except UserIsBlockedError:
                    shadow_banned.add(session)
                    await bot.send_message(user_id, f"⚠️ {session} banlandi! Task to‘xtatildi.")
                    return
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
    if task: task.cancel()
    if client: await client.disconnect()
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
