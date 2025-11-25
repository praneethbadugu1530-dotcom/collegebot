import os
import sqlite3
import csv
from datetime import datetime, date
from io import BytesIO
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    CallbackQueryHandler,
)

# ---------------- CONFIG ----------------
TOKEN = "8313663061:AAGNOh_rUKYbiRPDDRaxYvsl6UDdq4J3UbM"
ADMIN_IDS = {7126603988}
BROADCAST_GROUP_ID = None
REG_PASSWORD = None
DB_PATH = "college_bot_complete.db"
NOTES_DIR = "notes"
FLYER_LOCAL_PATH = "poster.jpg"   # make sure you upload and add correct filename
# -----------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

os.makedirs(NOTES_DIR, exist_ok=True)

# -------- DATABASE --------
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    full_name TEXT,
    roll TEXT,
    college TEXT,
    registered_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    att_date TEXT,
    created_at TEXT,
    UNIQUE(tg_id, att_date)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    posted_by INTEGER,
    posted_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    when_datetime TEXT,
    venue TEXT,
    description TEXT,
    created_by INTEGER,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS rsvps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    tg_id INTEGER,
    status TEXT,
    created_at TEXT,
    UNIQUE(event_id, tg_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    file_path TEXT,
    uploaded_by INTEGER,
    uploaded_at TEXT
)
""")
conn.commit()

# -------- HELPERS --------

def is_admin(uid):
    return uid in ADMIN_IDS

def register_user(tg_id, full, roll):
    cur.execute(
        "INSERT OR REPLACE INTO users (tg_id, full_name, roll, college, registered_at) VALUES (?, ?, ?, ?, ?)",
        (tg_id, full, roll, "MIC College of Technology, Vijayawada", datetime.utcnow().isoformat())
    )
    conn.commit()

def get_user(tg_id):
    cur.execute("SELECT tg_id, full_name, roll, college, registered_at FROM users WHERE tg_id=?", (tg_id,))
    return cur.fetchone()

def add_attendance(tg_id):
    today = date.today().isoformat()
    try:
        cur.execute("INSERT INTO attendance (tg_id, att_date, created_at) VALUES (?, ?, ?)",
                    (tg_id, today, datetime.utcnow().isoformat()))
        conn.commit()
        return True
    except:
        return False

def count_attendance(tg_id):
    cur.execute("SELECT COUNT(*) FROM attendance WHERE tg_id=?", (tg_id,))
    return cur.fetchone()[0]


# -------- KEYBOARD --------
def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("/register"), KeyboardButton("/myinfo")],
            [KeyboardButton("/attendance"), KeyboardButton("/notices")],
            [KeyboardButton("/events"), KeyboardButton("/notes")],
        ],
        resize_keyboard=True
    )

# -------- HANDLERS --------

def start(update, context):
    u = update.effective_user
    update.message.reply_text(
        f"Hello {u.first_name}! Welcome to MIC College Bot.",
        reply_markup=main_keyboard()
    )

def new_member(update, context):
    for m in update.message.new_chat_members:
        update.message.reply_text(f"Welcome {m.first_name}! Use /register <ROLL>")

def register_cmd(update, context):
    user = update.effective_user
    args = context.args

    if not args:
        update.message.reply_text("Usage: /register <ROLL>")
        return

    roll = args[0]
    full = f"{user.first_name} {user.last_name or ''}".strip()

    register_user(user.id, full, roll)
    update.message.reply_text("Registered successfully!")

def myinfo_cmd(update, context):
    row = get_user(update.effective_user.id)
    if not row:
        update.message.reply_text("You are not registered.")
        return

    _, full, roll, college, reg_at = row
    att = count_attendance(update.effective_user.id)

    update.message.reply_text(
        f"Name: {full}\nRoll: {roll}\nCollege: {college}\nRegistered: {reg_at}\nAttendance: {att}"
    )

def attendance_cmd(update, context):
    if not get_user(update.effective_user.id):
        update.message.reply_text("Register first using /register")
        return

    if add_attendance(update.effective_user.id):
        update.message.reply_text("Attendance marked.")
    else:
        update.message.reply_text("Already marked today.")

# -------- NOTES SYSTEM --------

def add_note_cmd(update, context):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Admins only.")
        return

    msg = update.message.reply_to_message
    if not msg or not msg.document:
        update.message.reply_text("Reply to a PDF file.")
        return

    title = " ".join(context.args)
    if not title:
        update.message.reply_text("Usage: reply to PDF → /add_note <title>")
        return

    doc = msg.document
    file = context.bot.getFile(doc.file_id)

    filename = f"{int(datetime.utcnow().timestamp())}_{doc.file_name}"
    path = os.path.join(NOTES_DIR, filename)

    file.download(custom_path=path)

    cur.execute(
        "INSERT INTO notes (title, file_path, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?)",
        (title, path, uid, datetime.utcnow().isoformat())
    )
    conn.commit()

    update.message.reply_text("Note saved successfully!")

def notes_list(update, context):
    cur.execute("SELECT id, title FROM notes ORDER BY uploaded_at DESC")
    rows = cur.fetchall()

    if not rows:
        update.message.reply_text("No notes available.")
        return

    kb = [[InlineKeyboardButton(title, callback_data=f"note:{nid}")] for nid, title in rows]
    update.message.reply_text("Choose a note:", reply_markup=InlineKeyboardMarkup(kb))

def notes_get(update, context):
    q = update.callback_query
    nid = int(q.data.split(":")[1])

    cur.execute("SELECT file_path, title FROM notes WHERE id=?", (nid,))
    row = cur.fetchone()

    if not row:
        q.answer("Not found")
        return

    path, title = row

    with open(path, "rb") as f:
        context.bot.send_document(
            chat_id=q.message.chat_id,
            document=f,
            filename=os.path.basename(path),
            caption=title
        )
    q.answer()


# -------- MAIN --------
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("register", register_cmd, pass_args=True))
    dp.add_handler(CommandHandler("myinfo", myinfo_cmd))
    dp.add_handler(CommandHandler("attendance", attendance_cmd))

    dp.add_handler(CommandHandler("add_note", add_note_cmd, pass_args=True))
    dp.add_handler(CommandHandler("notes", notes_list))
    dp.add_handler(CallbackQueryHandler(notes_get, pattern=r"^note:"))

    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_member))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
