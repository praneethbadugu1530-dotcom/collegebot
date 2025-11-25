# college_bot_complete.py
"""
College Bot — Full single-file:
- Welcome messages (private + new group members)
- Auto-broadcast notices to group (optional)
- Limited registration (optional password)
- Keyboard menu
- Notes system (Option C): admins reply to a PDF with /add_note Title to upload notes;
  students download via /notes and inline buttons.
- All other features: register, myinfo, attendance, notices, events+RSVP, poster, export CSV, delete notice
Requires: pip install python-telegram-bot==13.15
"""

import imghdr
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

# ---------------- CONFIG (update these) ----------------
TOKEN = "8313663061:AAGNOh_rUKYbiRPDDRaxYvsl6UDdq4J3UbM"         # <-- PASTE your BotFather token here
ADMIN_IDS = {7126603988}                 # <-- put your Telegram numeric id(s) here
BROADCAST_GROUP_ID = None               # <-- set to group id (int) to auto-broadcast notices (or None)
REG_PASSWORD = None                     # <-- set a password string if you want restricted registration
DB_PATH = "college_bot_complete.db"
FLYER_LOCAL_PATH = "/mnt/data/null-20251120-WA0011.jpg"  # poster you uploaded (already present)
NOTES_DIR = "notes"                     # local folder where uploaded PDFs will be stored
# ------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ensure notes dir exists
os.makedirs(NOTES_DIR, exist_ok=True)

# -------- DB setup --------
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

# -------- helpers --------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def register_user(tg_id, full_name, roll, college="MIC College of Technology, Vijayawada"):
    cur.execute(
        "INSERT OR REPLACE INTO users (tg_id, full_name, roll, college, registered_at) VALUES (?, ?, ?, ?, ?)",
        (tg_id, full_name, roll, college, datetime.utcnow().isoformat()),
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
    except Exception:
        return False

def count_attendance(tg_id):
    cur.execute("SELECT COUNT(*) FROM attendance WHERE tg_id=?", (tg_id,))
    return cur.fetchone()[0]

def post_notice_db(title, body, posted_by):
    cur.execute("INSERT INTO notices (title, body, posted_by, posted_at) VALUES (?, ?, ?, ?)",
                (title, body, posted_by, datetime.utcnow().isoformat()))
    conn.commit()
    return cur.lastrowid

def list_notices(limit=10):
    cur.execute("SELECT id, title, body, posted_at FROM notices ORDER BY posted_at DESC LIMIT ?", (limit,))
    return cur.fetchall()

def create_event_db(title, when_dt_iso, venue, description, created_by):
    cur.execute("INSERT INTO events (title, when_datetime, venue, description, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (title, when_dt_iso, venue, description, created_by, datetime.utcnow().isoformat()))
    conn.commit()
    return cur.lastrowid

def list_events_db():
    cur.execute("SELECT id, title, when_datetime, venue, description FROM events ORDER BY when_datetime ASC")
    return cur.fetchall()

def rsvp_event_db(event_id, tg_id, status="yes"):
    try:
        cur.execute("INSERT INTO rsvps (event_id, tg_id, status, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, tg_id, status, datetime.utcnow().isoformat()))
        conn.commit()
        return True
    except Exception:
        cur.execute("UPDATE rsvps SET status=?, created_at=? WHERE event_id=? AND tg_id=?",
                    (status, datetime.utcnow().isoformat(), event_id, tg_id))
        conn.commit()
        return True

def count_rsvps(event_id):
    cur.execute("SELECT COUNT(*) FROM rsvps WHERE event_id=? AND status='yes'", (event_id,))
    return cur.fetchone()[0]

def add_note_db(title, file_path, uploaded_by):
    cur.execute("INSERT INTO notes (title, file_path, uploaded_by, uploaded_at) VALUES (?, ?, ?, ?)",
                (title, file_path, uploaded_by, datetime.utcnow().isoformat()))
    conn.commit()
    return cur.lastrowid

def list_notes_db(limit=50):
    cur.execute("SELECT id, title, file_path, uploaded_at FROM notes ORDER BY uploaded_at DESC LIMIT ?", (limit,))
    return cur.fetchall()

# -------- Menu keyboard --------
def main_keyboard():
    kb = [
        [KeyboardButton("/register"), KeyboardButton("/myinfo")],
        [KeyboardButton("/attendance"), KeyboardButton("/notices")],
        [KeyboardButton("/events"), KeyboardButton("/notes")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# -------- Bot Handlers --------

def start(update: Update, context: CallbackContext):
    user = update.effective_user
    # send welcome and keyboard
    text = (f"Hello {user.first_name or ''}! 👋\nWelcome to MIC College Bot.\n\n"
            "Use the keyboard below or type a command.\nIf you are a student, please register using /register <ROLL>.")
    update.message.reply_text(text, reply_markup=main_keyboard())

# welcome message when a new member joins a group
def new_member_welcome(update: Update, context: CallbackContext):
    for m in update.message.new_chat_members:
        try:
            update.message.reply_text(f"Welcome {m.first_name}! Please register with /register <ROLL> (in this bot).")
        except Exception:
            pass

# ---------- Registration ----------
def register_cmd(update: Update, context: CallbackContext):
    user = update.effective_user
    args = context.args
    if not args:
        update.message.reply_text("Usage: /register <ROLL> or /register <ROLL> <PASSWORD> (if required)")
        return
    roll = args[0].strip()
    if REG_PASSWORD:
        if len(args) < 2:
            update.message.reply_text("This bot requires a registration password. Usage: /register <ROLL> <PASSWORD>")
            return
        pwd = args[1]
        if pwd != REG_PASSWORD:
            update.message.reply_text("Incorrect registration password.")
            return
    full = f"{user.first_name or ''} {(user.last_name or '').strip()}".strip()
    register_user(user.id, full, roll)
    update.message.reply_text(f"Registered ✅\nName: {full}\nRoll: {roll}")

def myinfo_cmd(update: Update, context: CallbackContext):
    row = get_user(update.effective_user.id)
    if not row:
        update.message.reply_text("You are not registered. Use /register <roll> to register.")
        return
    _, full_name, roll, college, reg_at = row
    attendance_count = count_attendance(update.effective_user.id)
    update.message.reply_text(f"Name: {full_name}\nRoll: {roll}\nCollege: {college}\nRegistered at: {reg_at}\nAttendance: {attendance_count}")

# ---------- Attendance ----------
def attendance_cmd(update: Update, context: CallbackContext):
    row = get_user(update.effective_user.id)
    if not row:
        update.message.reply_text("You are not registered. Register with /register <roll> first.")
        return
    ok = add_attendance(update.effective_user.id)
    if ok:
        update.message.reply_text("Attendance marked for today ✅")
    else:
        update.message.reply_text("You already marked attendance today. ✋")

# ---------- Notices ----------
def post_notice_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("You are not authorized to post notices.")
        return
    text = " ".join(context.args).strip()
    if "|" not in text:
        update.message.reply_text("Usage: /post_notice Title|Body")
        return
    title, body = [p.strip() for p in text.split("|", 1)]
    nid = post_notice_db(title, body, uid)
    update.message.reply_text(f"Notice posted (id: {nid}) ✅")
    # broadcast to group if configured
    if BROADCAST_GROUP_ID:
        try:
            context.bot.send_message(chat_id=BROADCAST_GROUP_ID, text=f"*NOTICE*: *{title}*\n\n{body}", parse_mode="Markdown")
        except Exception as e:
            logger.warning("Failed to broadcast notice: %s", e)

def list_notices_cmd(update: Update, context: CallbackContext):
    limit = 10
    if context.args:
        try:
            limit = int(context.args[0])
        except:
            pass
    rows = list_notices(limit)
    if not rows:
        update.message.reply_text("No notices yet.")
        return
    out = []
    for nid, title, body, posted_at in rows:
        short = body if len(body) < 400 else body[:400] + "..."
        out.append(f"[{nid}] *{title}*\n{short}\n_posted: {posted_at}_")
    update.message.reply_text("\n\n".join(out), parse_mode="Markdown")

def delete_notice_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Only admins can delete notices.")
        return
    if not context.args:
        update.message.reply_text("Usage: /delete_notice <id>")
        return
    try:
        nid = int(context.args[0])
    except:
        update.message.reply_text("Notice id must be a number.")
        return
    cur.execute("DELETE FROM notices WHERE id=?", (nid,))
    conn.commit()
    update.message.reply_text(f"Deleted notice {nid} ✅")

# ---------- Events & RSVP ----------
def create_event_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Only admins can create events.")
        return
    text = " ".join(context.args)
    if "|" not in text:
        update.message.reply_text("Usage: /create_event Title|YYYY-MM-DD HH:MM|Venue|Description")
        return
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 4:
        update.message.reply_text("Provide all fields: Title|YYYY-MM-DD HH:MM|Venue|Description")
        return
    title, when_dt, venue, description = parts
    try:
        dt = datetime.strptime(when_dt, "%Y-%m-%d %H:%M")
        iso = dt.isoformat()
    except Exception:
        update.message.reply_text("Date format invalid. Use YYYY-MM-DD HH:MM")
        return
    eid = create_event_db(title, iso, venue, description, uid)
    update.message.reply_text(f"Event created (id: {eid}) ✅")

def events_cmd(update: Update, context: CallbackContext):
    rows = list_events_db()
    if not rows:
        update.message.reply_text("No upcoming events.")
        return
    for eid, title, when_dt, venue, description in rows:
        count_yes = count_rsvps(eid)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("RSVP ✅", callback_data=f"rsvp_yes:{eid}"),
            InlineKeyboardButton("Cancel ❌", callback_data=f"rsvp_no:{eid}")
        ]])
        update.message.reply_text(f"*[{eid}]* {title}\nWhen: {when_dt}\nVenue: {venue}\n{description}\nRSVPs: {count_yes}",
                                  parse_mode="Markdown", reply_markup=kb)

def callback_query_handler(update: Update, context: CallbackContext):
    q = update.callback_query
    data = q.data
    if data.startswith("rsvp_yes:") or data.startswith("rsvp_no:"):
        action, sid = data.split(":")
        eid = int(sid)
        if action == "rsvp_yes":
            rsvp_event_db(eid, q.from_user.id, status="yes")
            q.answer("RSVP recorded ✅")
            q.edit_message_reply_markup(None)
            q.message.reply_text(f"{q.from_user.first_name} RSVP'd ✅")
        else:
            rsvp_event_db(eid, q.from_user.id, status="no")
            q.answer("Cancelled RSVP")
            q.edit_message_reply_markup(None)
            q.message.reply_text(f"{q.from_user.first_name} cancelled RSVP ❌")
    else:
        q.answer()

# ---------- Poster ----------
def poster_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Only admins can use /poster.")
        return
    try:
        with open(FLYER_LOCAL_PATH, "rb") as f:
            context.bot.send_photo(chat_id=update.effective_chat.id, photo=f,
                                   caption="Join: Create Your Own Telegram Chatbot")
    except Exception as e:
        update.message.reply_text("Failed to send poster: " + str(e))

# ---------- Export CSV ----------
def export_csv_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Admins only.")
        return
    try:
        # users
        cur.execute("SELECT tg_id, full_name, roll, college, registered_at FROM users")
        users = cur.fetchall()
        buf = BytesIO()
        w = csv.writer(buf)
        w.writerow(["tg_id", "full_name", "roll", "college", "registered_at"])
        w.writerows(users)
        buf.seek(0)
        context.bot.send_document(chat_id=update.effective_chat.id, document=buf, filename="users.csv")
    except Exception as e:
        update.message.reply_text("Export failed: " + str(e))

# ---------- Notes system (Option C) ----------
# Admin: reply to a PDF file message with command: /add_note Title
# Example: send PDF to bot, then reply to that message with: /add_note Unit 1 - Introduction
def add_note_cmd(update: Update, context: CallbackContext):
    uid = update.effective_user.id
    if not is_admin(uid):
        update.message.reply_text("Only admins can add notes.")
        return

    # Must be replied to a message containing a document (pdf)
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        update.message.reply_text("Please reply to a PDF file message with /add_note <Title>.")
        return

    title = " ".join(context.args).strip()
    if not title:
        update.message.reply_text("Usage: reply to a PDF and send: /add_note <Title>")
        return

    doc = update.message.reply_to_message.document
    file_id = doc.file_id
    file_name = doc.file_name or f"note_{int(datetime.utcnow().timestamp())}.pdf"
    # safe unique filename
    safe_name = f"{int(datetime.utcnow().timestamp())}_{file_name}"
    local_path = os.path.join(NOTES_DIR, safe_name)

    # download file
    try:
        f = context.bot.getFile(file_id)
        f.download(custom_path=local_path)
        nid = add_note_db(title, local_path, uid)
        update.message.reply_text(f"Note saved as id {nid} and stored locally.")
    except Exception as e:
        logger.exception("Failed to download note")
        update.message.reply_text("Failed to save note: " + str(e))

# List notes for users
def notes_list_cmd(update: Update, context: CallbackContext):
    rows = list_notes_db(50)
    if not rows:
        update.message.reply_text("No notes available.")
        return
    buttons = []
    messages = []
    # We'll show up to 25 notes with inline buttons; each row -> one line and a button
    for nid, title, file_path, uploaded_at in rows[:25]:
        buttons.append([InlineKeyboardButton(f"{title}", callback_data=f"note_get:{nid}")])
        messages.append(f"[{nid}] {title} (uploaded: {uploaded_at})")
    kb = InlineKeyboardMarkup(buttons)
    update.message.reply_text("Available notes (tap a button to download):", reply_markup=kb)

# Send note file when button pressed
def notes_callback_handler(update: Update, context: CallbackContext):
    q = update.callback_query
    data = q.data
    if not data.startswith("note_get:"):
        q.answer()
        return
    try:
        nid = int(data.split(":", 1)[1])
    except:
        q.answer("Invalid note id")
        return
    cur.execute("SELECT file_path, title FROM notes WHERE id=?", (nid,))
    row = cur.fetchone()
    if not row:
        q.answer("Note not found")
        return
    file_path, title = row
    # send the file
    try:
        with open(file_path, "rb") as f:
            context.bot.send_document(chat_id=q.message.chat_id, document=f, filename=os.path.basename(file_path), caption=title)
        q.answer("Sending file...")
    except Exception as e:
        logger.exception("Failed to send note")
        q.answer("Failed to send file: " + str(e))

# ---------- Unknown command ----------
def unknown_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("Unknown command. Use /start to see options.")

# ---------- Main ----------
def main():
    if TOKEN.strip().startswith("PASTE") or TOKEN.strip() == "":
        print("ERROR: Put your bot TOKEN in the script and restart.")
        return

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # basic commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", start))  # same help
    dp.add_handler(CommandHandler("register", register_cmd, pass_args=True))
    dp.add_handler(CommandHandler("myinfo", myinfo_cmd))
    dp.add_handler(CommandHandler("attendance", attendance_cmd))

    # notices
    dp.add_handler(CommandHandler("post_notice", post_notice_cmd, pass_args=True))
    dp.add_handler(CommandHandler("notices", list_notices_cmd, pass_args=True))
    dp.add_handler(CommandHandler("delete_notice", delete_notice_cmd, pass_args=True))

    # events
    dp.add_handler(CommandHandler("create_event", create_event_cmd, pass_args=True))
    dp.add_handler(CommandHandler("events", events_cmd))
    dp.add_handler(CallbackQueryHandler(callback_query_handler, pattern=r"^rsvp_"))

    # poster & export
    dp.add_handler(CommandHandler("poster", poster_cmd))
    dp.add_handler(CommandHandler("export_csv", export_csv_cmd))

    # notes
    dp.add_handler(CommandHandler("add_note", add_note_cmd, pass_args=True))  # admin: reply to PDF & call this
    dp.add_handler(CommandHandler("notes", notes_list_cmd))
    dp.add_handler(CallbackQueryHandler(notes_callback_handler, pattern=r"^note_get:"))

    # welcome in groups - new members
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_member_welcome))

    # unknown
    dp.add_handler(MessageHandler(Filters.command, unknown_cmd))

    logger.info("Starting College Bot (complete)...")
    updater.start_polling()
    logger.info("Bot started.")
    updater.idle()

if __name__ == "__main__":
    main()
