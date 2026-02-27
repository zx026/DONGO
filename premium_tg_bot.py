import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)

# ╔══════════════════════════════════════════════╗
# ║              ⚙️  CONFIG ZONE                 ║
# ╚══════════════════════════════════════════════╝
BOT_TOKEN      = "YOUR_BOT_TOKEN_HERE"       # @BotFather se lena
ZEPH_API_KEY   = "ZEPH-4O1YD"               # Zephrex API Key

OWNER_ID       = 123456789                   # Owner ka Telegram User ID
OWNER_USERNAME = "@YourUsername"             # Owner ka username (buy ke liye)
CHANNEL_LINK   = "https://t.me/YourChannel" # Apna channel link
CHANNEL_NAME   = "📢 Official Channel"       # Channel ka naam

# ─── Premium Plans ───
PLANS = {
    "trial"   : {"days": 1,   "label": "🆓 1 Din Trial",      "price": "FREE"},
    "weekly"  : {"days": 7,   "label": "📅 7 Din",            "price": "₹49"},
    "monthly" : {"days": 30,  "label": "📆 30 Din",           "price": "₹149"},
    "lifetime": {"days": 9999,"label": "♾️ Lifetime",         "price": "₹499"},
}
# ════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ╔══════════════════════════════════════════════╗
# ║               🗄️  DATABASE                  ║
# ╚══════════════════════════════════════════════╝
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            username    TEXT,
            full_name   TEXT,
            status      TEXT DEFAULT 'pending',
            plan        TEXT DEFAULT 'none',
            expires_at  TEXT,
            joined_at   TEXT
        )
    """)

    # Records table
    c.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            term         TEXT UNIQUE,
            number       TEXT,
            country      TEXT,
            country_code TEXT,
            added_at     TEXT
        )
    """)

    # Pending requests
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER,
            username   TEXT,
            full_name  TEXT,
            plan       TEXT,
            requested_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def upsert_user(user_id, username, full_name):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, username, full_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            full_name = excluded.full_name
    """, (user_id, username or "N/A", full_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def approve_user(user_id, plan):
    days = PLANS[plan]["days"]
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""
        UPDATE users SET status='approved', plan=?, expires_at=?
        WHERE user_id=?
    """, (plan, expires, user_id))
    conn.commit()
    conn.close()

def reject_user(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status='rejected' WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def revoke_user(user_id):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status='revoked', plan='none', expires_at=NULL WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_premium(user_id):
    """Check karo user approved hai aur expire nahi hua"""
    row = get_user(user_id)
    if not row:
        return False
    status     = row[3]
    expires_at = row[5]
    if status != "approved":
        return False
    if expires_at and expires_at != "9999-12-31 00:00":
        if datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M"):
            revoke_user(user_id)
            return False
    return True

def save_request(user_id, username, full_name, plan):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO requests (user_id, username, full_name, plan, requested_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username or "N/A", full_name, plan, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY joined_at DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def save_record(term, number, country, country_code):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO records (term, number, country, country_code, added_at)
        VALUES (?, ?, ?, ?, ?)
    """, (str(term), number, country, country_code, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_record(term):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM records WHERE term = ?", (str(term),))
    row = c.fetchone()
    conn.close()
    return row

# ╔══════════════════════════════════════════════╗
# ║              🌐  API CALL                    ║
# ╚══════════════════════════════════════════════╝
def fetch_from_api(term):
    try:
        r = requests.get(
            "https://www.zephrexdigital.site/api",
            params={"key": ZEPH_API_KEY, "type": "TG_NUM", "term": term},
            timeout=10
        )
        data = r.json()
        if data.get("status"):
            d = data["data"]
            return {
                "number"      : d.get("number", "N/A"),
                "country"     : d.get("country", "N/A"),
                "country_code": d.get("country_code", "N/A"),
            }
    except Exception as e:
        logging.error(f"API Error: {e}")
    return None

# ╔══════════════════════════════════════════════╗
# ║           🎨  KEYBOARD BUILDERS              ║
# ╚══════════════════════════════════════════════╝
def main_keyboard():
    """Sabko dikhne wala keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
            InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
        ]
    ])

def buy_keyboard():
    """Non-premium users ke liye"""
    buttons = []
    for plan_key, plan in PLANS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{plan['label']} — {plan['price']}",
                callback_data=f"buy_{plan_key}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("👑 Owner se Contact karo", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
        InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
    ])
    return InlineKeyboardMarkup(buttons)

def admin_approve_keyboard(user_id):
    """Owner ke liye approve buttons"""
    buttons = []
    for plan_key, plan in PLANS.items():
        buttons.append([
            InlineKeyboardButton(
                f"✅ Approve — {plan['label']}",
                callback_data=f"approve_{user_id}_{plan_key}"
            )
        ])
    buttons.append([
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}"),
    ])
    return InlineKeyboardMarkup(buttons)

# ╔══════════════════════════════════════════════╗
# ║              🤖  BOT HANDLERS                ║
# ╚══════════════════════════════════════════════╝
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    upsert_user(user.id, user.username, user.full_name)

    if is_premium(user.id):
        row = get_user(user.id)
        text = (
            f"✨ *Welcome Back, {user.first_name}!*\n\n"
            f"🏆 *Plan:* `{row[4].upper()}`\n"
            f"⏳ *Expires:* `{row[5]}`\n\n"
            f"📌 *Commands:*\n"
            f"🔍 `/lookup <id/username>` — Number dhundho\n"
            f"➕ `/add <id/username>` — API se add karo\n"
            f"📊 `/status` — Apna plan dekho"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

    else:
        text = (
            f"👋 *Namaste {user.first_name}!*\n\n"
            f"🔒 Ye bot *Premium* hai.\n"
            f"Access karne ke liye Owner se subscription lo!\n\n"
            f"💎 *Plans Available:*\n"
            f"• 🆓 1 Din Trial — FREE\n"
            f"• 📅 7 Din — ₹49\n"
            f"• 📆 30 Din — ₹149\n"
            f"• ♾️ Lifetime — ₹499\n\n"
            f"👇 *Neeche se plan chunke request bhejo!*"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=buy_keyboard())


async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = get_user(user.id)

    if not row:
        await update.message.reply_text("❌ Aap registered nahi hain. /start karo.", reply_markup=main_keyboard())
        return

    status_emoji = {"approved": "✅", "pending": "⏳", "rejected": "❌", "revoked": "🚫"}.get(row[3], "❓")
    text = (
        f"📊 *Aapka Status*\n\n"
        f"👤 Name    : {row[2]}\n"
        f"🆔 ID      : `{row[0]}`\n"
        f"📌 Status  : {status_emoji} `{row[3].upper()}`\n"
        f"🏆 Plan    : `{row[4].upper()}`\n"
        f"⏳ Expires : `{row[5] or 'N/A'}`\n"
        f"📅 Joined  : `{row[6]}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_premium(user.id):
        await update.message.reply_text(
            "🔒 *Ye feature Premium users ke liye hai!*\n\n"
            f"👑 Owner se subscribe karo: {OWNER_USERNAME}",
            parse_mode="Markdown",
            reply_markup=buy_keyboard()
        )
        return

    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/lookup <user_id ya username>`", parse_mode="Markdown")
        return

    term = ctx.args[0].replace("@", "").strip()
    msg  = await update.message.reply_text(f"🔍 *{term}* dhundh raha hoon...", parse_mode="Markdown")

    row = get_record(term)
    if row:
        text = (
            f"✅ *Record Mila! (DB se)*\n\n"
            f"🆔 Term       : `{row[1]}`\n"
            f"📱 Number     : `{row[2]}`\n"
            f"🌍 Country    : {row[3]}\n"
            f"📞 Code       : {row[4]}\n"
            f"🕐 Added At   : {row[5]}"
        )
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_keyboard())
        return

    result = fetch_from_api(term)
    if result:
        save_record(term, result["number"], result["country"], result["country_code"])
        text = (
            f"✅ *Number Mila!*\n\n"
            f"🆔 Term       : `{term}`\n"
            f"📱 Number     : `{result['number']}`\n"
            f"🌍 Country    : {result['country']}\n"
            f"📞 Code       : {result['country_code']}\n"
            f"💾 _Record save ho gaya!_"
        )
    else:
        text = f"❌ `{term}` ke liye koi data nahi mila."

    await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not is_premium(user.id):
        await update.message.reply_text(
            "🔒 *Ye feature Premium users ke liye hai!*",
            parse_mode="Markdown",
            reply_markup=buy_keyboard()
        )
        return

    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/add <user_id ya username>`", parse_mode="Markdown")
        return

    term = ctx.args[0].replace("@", "").strip()
    msg  = await update.message.reply_text(f"⏳ Fetch kar raha hoon: `{term}`...", parse_mode="Markdown")

    result = fetch_from_api(term)
    if result:
        save_record(term, result["number"], result["country"], result["country_code"])
        text = (
            f"✅ *Saved Successfully!*\n\n"
            f"🆔 Term   : `{term}`\n"
            f"📱 Number : `{result['number']}`\n"
            f"🌍 Country: {result['country']} {result['country_code']}"
        )
    else:
        text = f"❌ API se data nahi aaya `{term}` ke liye."

    await msg.edit_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


# ─── ADMIN COMMANDS ───────────────────────────
async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Sirf Owner ye dekh sakta hai!")
        return

    rows = get_all_users()
    if not rows:
        await update.message.reply_text("📭 Abhi koi user nahi hai.")
        return

    approved = [r for r in rows if r[3] == "approved"]
    pending  = [r for r in rows if r[3] == "pending"]
    rejected = [r for r in rows if r[3] in ("rejected", "revoked")]

    text = (
        f"👥 *Total Users: {len(rows)}*\n"
        f"✅ Approved : {len(approved)}\n"
        f"⏳ Pending  : {len(pending)}\n"
        f"❌ Rejected : {len(rejected)}\n\n"
    )

    for r in rows[:15]:
        em = {"approved":"✅","pending":"⏳","rejected":"❌","revoked":"🚫"}.get(r[3],"❓")
        text += f"{em} `{r[0]}` | @{r[1]} | {r[4]} | {r[5] or 'N/A'}\n"

    if len(rows) > 15:
        text += f"\n_...aur {len(rows)-15} users hain_"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())


async def admin_approve_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Manual approve: /approve <user_id> <plan>"""
    if update.effective_user.id != OWNER_ID:
        return

    if len(ctx.args) < 2:
        await update.message.reply_text("⚠️ Usage: `/approve <user_id> <trial/weekly/monthly/lifetime>`", parse_mode="Markdown")
        return

    uid  = int(ctx.args[0])
    plan = ctx.args[1].lower()
    if plan not in PLANS:
        await update.message.reply_text("❌ Plan galat hai. Use: trial/weekly/monthly/lifetime")
        return

    approve_user(uid, plan)
    await update.message.reply_text(f"✅ User `{uid}` ko *{PLANS[plan]['label']}* plan approve ho gaya!", parse_mode="Markdown")

    try:
        await ctx.bot.send_message(
            uid,
            f"🎉 *Congratulations!*\n\n"
            f"✅ Aapka access *approve* ho gaya!\n"
            f"🏆 Plan: *{PLANS[plan]['label']}*\n"
            f"⏳ Expires: *{(datetime.now() + timedelta(days=PLANS[plan]['days'])).strftime('%Y-%m-%d')}*\n\n"
            f"_/start karke bot use karo!_",
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
    except:
        pass


async def admin_revoke_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/revoke <user_id>`", parse_mode="Markdown")
        return
    uid = int(ctx.args[0])
    revoke_user(uid)
    await update.message.reply_text(f"🚫 User `{uid}` ka access revoke ho gaya!", parse_mode="Markdown")
    try:
        await ctx.bot.send_message(uid, "🚫 Aapka premium access revoke ho gaya.\nOwner se contact karo.", reply_markup=buy_keyboard())
    except:
        pass


async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner sabko message bhej sakta hai"""
    if update.effective_user.id != OWNER_ID:
        return
    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast <message>`", parse_mode="Markdown")
        return
    msg_text = " ".join(ctx.args)
    rows = get_all_users()
    sent = 0
    for r in rows:
        try:
            await ctx.bot.send_message(r[0], f"📢 *Owner ka Message:*\n\n{msg_text}", parse_mode="Markdown", reply_markup=main_keyboard())
            sent += 1
        except:
            pass
    await update.message.reply_text(f"✅ {sent}/{len(rows)} logon ko message mila!")


# ─── CALLBACK QUERIES ─────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = query.from_user
    data  = query.data

    # ── Buy request ──
    if data.startswith("buy_"):
        plan = data.replace("buy_", "")
        if plan not in PLANS:
            return

        upsert_user(user.id, user.username, user.full_name)
        save_request(user.id, user.username, user.full_name, plan)

        await query.edit_message_text(
            f"📩 *Request Bhej Di Gayi!*\n\n"
            f"🏆 Plan : *{PLANS[plan]['label']}*\n"
            f"💰 Price: *{PLANS[plan]['price']}*\n\n"
            f"⏳ Owner approve karega jald hi!\n"
            f"👑 Contact: {OWNER_USERNAME}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
                InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
            ]])
        )

        # Owner ko notify karo
        try:
            await ctx.bot.send_message(
                OWNER_ID,
                f"🔔 *Naya Subscribe Request!*\n\n"
                f"👤 Name   : {user.full_name}\n"
                f"🆔 ID     : `{user.id}`\n"
                f"📌 User   : @{user.username or 'N/A'}\n"
                f"🏆 Plan   : *{PLANS[plan]['label']}* ({PLANS[plan]['price']})\n"
                f"🕐 Time   : {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                parse_mode="Markdown",
                reply_markup=admin_approve_keyboard(user.id)
            )
        except Exception as e:
            logging.error(f"Owner notify error: {e}")

    # ── Admin Approve ──
    elif data.startswith("approve_"):
        if query.from_user.id != OWNER_ID:
            await query.answer("🚫 Sirf Owner approve kar sakta hai!", show_alert=True)
            return
        parts   = data.split("_")
        uid     = int(parts[1])
        plan    = parts[2]
        approve_user(uid, plan)

        await query.edit_message_text(
            f"✅ *Approved!*\n\n"
            f"🆔 User ID : `{uid}`\n"
            f"🏆 Plan    : *{PLANS[plan]['label']}*\n"
            f"💰 Price   : {PLANS[plan]['price']}",
            parse_mode="Markdown"
        )

        try:
            await ctx.bot.send_message(
                uid,
                f"🎉 *Congratulations!*\n\n"
                f"✅ Aapka *{PLANS[plan]['label']}* plan activate ho gaya!\n"
                f"⏳ Expires: *{(datetime.now() + timedelta(days=PLANS[plan]['days'])).strftime('%Y-%m-%d')}*\n\n"
                f"🔍 Ab `/lookup` ya `/add` use karo!",
                parse_mode="Markdown",
                reply_markup=main_keyboard()
            )
        except:
            pass

    # ── Admin Reject ──
    elif data.startswith("reject_"):
        if query.from_user.id != OWNER_ID:
            await query.answer("🚫 Sirf Owner reject kar sakta hai!", show_alert=True)
            return
        uid = int(data.replace("reject_", ""))
        reject_user(uid)

        await query.edit_message_text(f"❌ User `{uid}` reject ho gaya.", parse_mode="Markdown")

        try:
            await ctx.bot.send_message(
                uid,
                f"❌ Aapki request *reject* ho gayi.\n\n"
                f"Koi issue ho to Owner se contact karo: {OWNER_USERNAME}",
                parse_mode="Markdown",
                reply_markup=buy_keyboard()
            )
        except:
            pass


# ─── Direct Message Handler ───────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip().replace("@", "")

    if not is_premium(user.id):
        await update.message.reply_text(
            f"🔒 *Bot Premium hai!*\n\n"
            f"Access ke liye Owner se contact karo: {OWNER_USERNAME}\n\n"
            f"👇 Neeche se plan subscribe karo:",
            parse_mode="Markdown",
            reply_markup=buy_keyboard()
        )
        return

    await update.message.reply_text(f"🔍 *{text}* check kar raha hoon...", parse_mode="Markdown")

    row = get_record(text)
    if row:
        msg = (
            f"✅ *Record Mila!*\n\n"
            f"🆔 Term    : `{row[1]}`\n"
            f"📱 Number  : `{row[2]}`\n"
            f"🌍 Country : {row[3]}\n"
            f"📞 Code    : {row[4]}\n"
            f"🕐 Added   : {row[5]}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())
        return

    result = fetch_from_api(text)
    if result:
        save_record(text, result["number"], result["country"], result["country_code"])
        msg = (
            f"✅ *Number Mila!*\n\n"
            f"🆔 Term    : `{text}`\n"
            f"📱 Number  : `{result['number']}`\n"
            f"🌍 Country : {result['country']}\n"
            f"📞 Code    : {result['country_code']}\n"
            f"💾 _Saved!_"
        )
    else:
        msg = f"❌ `{text}` ke liye koi data nahi mila."

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_keyboard())


# ╔══════════════════════════════════════════════╗
# ║                  🚀  MAIN                    ║
# ╚══════════════════════════════════════════════╝
def main():
    init_db()
    print("🤖 Premium Bot chal raha hai...")

    app = Application.builder().token(BOT_TOKEN).build()

    # User Commands
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("status",    status))
    app.add_handler(CommandHandler("lookup",    lookup))
    app.add_handler(CommandHandler("add",       add_cmd))

    # Admin/Owner Commands
    app.add_handler(CommandHandler("users",     admin_users))
    app.add_handler(CommandHandler("approve",   admin_approve_cmd))
    app.add_handler(CommandHandler("revoke",    admin_revoke_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()
