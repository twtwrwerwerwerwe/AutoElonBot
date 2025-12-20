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
API_ID = 39100604
API_HASH = "ca07a6a98a97f85f371d2b3d179ecd06"

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

# =================📱 RAQAMLAR BO'LIMI (TO'G'RILANGAN) =================

@dp.message_handler(lambda m: m.text == "📱 Raqamlar")
async def numbers_menu(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("➕ Raqam qo‘shish", "🗑 Raqam o‘chirish")
    kb.add("🏠 Asosiy menyu") # "Orqaga" o'rniga aniqroq nom
    await msg.answer("📱 Raqamlar bo‘limi", reply_markup=kb)

# Asosiy menyuga qaytish tugmasi uchun
@dp.message_handler(lambda m: m.text == "🏠 Asosiy menyu")
async def back_to_main(msg: types.Message):
    await main_menu(msg)

@dp.message_handler(lambda m: m.text == "➕ Raqam qo‘shish")
async def add_number(msg: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("⬅️ Orqaga")
    await msg.answer("📞 Telefon raqam kiriting (+998...)", reply_markup=kb)
    await AddNum.phone.set()

@dp.message_handler(state=AddNum.phone)
async def get_phone(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await numbers_menu(msg)
        return
    
    phone = msg.text.strip()
    session_name = phone.replace("+", "")
    
    # Yangi Samsung A16 modeli bilan client yaratish
    client = TelegramClient(
        f"{SESS_DIR}/{session_name}", 
        API_ID, 
        API_HASH,
        device_model="Samsung A16",
        system_version="15.0",
        app_version="10.3.0"
    )
    
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        await state.update_data(phone=phone, session=session_name, hash=sent.phone_code_hash)
        await AddNum.code.set()
        
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ Orqaga")
        await msg.answer("📨 SMS kodni yoki Telegramga kelgan kodni kiriting:", reply_markup=kb)
    except Exception as e:
        await msg.answer(f"❌ Xatolik yuz berdi: {e}")
        await state.finish()
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.code)
async def get_code(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await numbers_menu(msg)
        return
    
    d = await state.get_data()
    # d['session'] dan foydalanamiz, chunki bu funksiyada 'session' o'zgaruvchisi yo'q
    client = TelegramClient(
        f"{SESS_DIR}/{d['session']}", 
        API_ID, 
        API_HASH,
        device_model="Samsung A16",
        system_version="15.0",
        app_version="10.3.0"
    )
    
    await client.connect()
    try:
        code = msg.text.strip().replace(" ", "")
        await client.sign_in(d['phone'], code, phone_code_hash=d['hash'])
        
        with db() as c:
            c.execute("INSERT INTO numbers (user_id, session) VALUES (?,?)", (msg.from_user.id, d['session']))
        
        await msg.answer("✅ Akkaunt muvaffaqiyatli ulandi!")
        await state.finish()
        await numbers_menu(msg)
        
    except SessionPasswordNeededError:
        await AddNum.password.set()
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("⬅️ Orqaga")
        await msg.answer("🔐 Akkauntda 2-bosqichli parol bor. Parolni kiriting:", reply_markup=kb)
    except Exception as e:
        await msg.answer(f"❌ Kod xato yoki muddati o'tgan: {e}")
    finally:
        await client.disconnect()

@dp.message_handler(state=AddNum.password)
async def get_password(msg: types.Message, state: FSMContext):
    if msg.text == "⬅️ Orqaga":
        await state.finish()
        await numbers_menu(msg)
        return
    
    d = await state.get_data()
    client = TelegramClient(
        f"{SESS_DIR}/{d['session']}", 
        API_ID, 
        API_HASH,
        device_model="Samsung A16",
        system_version="15.0",
        app_version="10.3.0"
    )
    
    await client.connect()
    try:
        await client.sign_in(password=msg.text.strip())
        with db() as c:
            c.execute("INSERT INTO numbers (user_id, session) VALUES (?,?)", (msg.from_user.id, d['session']))
        await msg.answer("✅ Akkaunt (parol orqali) ulandi!")
        await state.finish()
        await numbers_menu(msg)
    except Exception as e:
        await msg.answer(f"❌ Parol noto‘g‘ri yoki xatolik: {e}")
    finally:
        await client.disconnect()

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
            kb.add(types.InlineKeyboardButton(f"{mark}{d.name[:30]}", callback_data=f"addgrp:{sess}:{d.id}"))
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
        with db() as c:
            c.execute(
                "DELETE FROM selected_groups WHERE user_id=? AND session=? AND group_id=?",
                (user_id, sess, gid)
            )
        prefix = ""
        await call.answer("❌ Olib tashlandi")
    else:
        with db() as c:
            c.execute(
                "INSERT INTO selected_groups VALUES (?,?,?,?)",
                (user_id, sess, gid, title)
            )
        prefix = "✅ "
        await call.answer("✅ Tanlandi")
    kb = call.message.reply_markup
    for row_btn in kb.inline_keyboard:
        btn = row_btn[0]
        if btn.callback_data == call.data:
            btn.text = prefix + title[:30]
    await call.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "back")
async def go_back(call: types.CallbackQuery):
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
