import logging
import sqlite3
import requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler,
    ConversationHandler
)

# ╔══════════════════════════════════════════════════════════════╗
# ║                    ⚙️  CONFIG ZONE                          ║
# ╚══════════════════════════════════════════════════════════════╝
BOT_TOKEN      = "YOUR_BOT_TOKEN_HERE"
ZEPH_API_KEY   = "ZEPH-4O1YD"

OWNER_ID       = 123456789
OWNER_USERNAME = "@YourUsername"
CHANNEL_LINK   = "https://t.me/YourChannel"
CHANNEL_NAME   = "📢 Official Channel"

# ─── UPI Details ───────────────────────────────────────────────
UPI_ID      = "yourname@ybl"
UPI_NAME    = "Your Name"
GPAY_NUM    = "9999999999"

# ─── Crypto Wallet Addresses ───────────────────────────────────
WALLETS = {
    "btc"  : "YOUR_BTC_WALLET_ADDRESS",          # Bitcoin
    "eth"  : "YOUR_ETH_WALLET_ADDRESS",          # Ethereum
    "usdt_trc20": "YOUR_USDT_TRC20_ADDRESS",     # USDT TRC20 (Tron)
    "usdt_erc20": "YOUR_USDT_ERC20_ADDRESS",     # USDT ERC20 (Ethereum)
    "ton"  : "YOUR_TON_WALLET_ADDRESS",          # TON
}

# ─── Plans ─────────────────────────────────────────────────────
PLANS = {
    "trial"   : {"days": 1,    "label": "🆓 1 Din Trial",  "price_inr": "FREE", "price_usd": "FREE",  "amount": 0},
    "weekly"  : {"days": 7,    "label": "📅 7 Din",        "price_inr": "₹49",  "price_usd": "$0.60", "amount": 49},
    "monthly" : {"days": 30,   "label": "📆 30 Din",       "price_inr": "₹149", "price_usd": "$1.80", "amount": 149},
    "lifetime": {"days": 9999, "label": "♾️ Lifetime",     "price_inr": "₹499", "price_usd": "$6.00", "amount": 499},
}

# Conversation states
WAITING_METHOD = 1
WAITING_SS     = 2
# ════════════════════════════════════════════════════════════════

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# ╔══════════════════════════════════════════════════════════════╗
# ║                    🗄️  DATABASE                             ║
# ╚══════════════════════════════════════════════════════════════╝
def init_db():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id    INTEGER PRIMARY KEY,
        username   TEXT,
        full_name  TEXT,
        status     TEXT DEFAULT 'free',
        plan       TEXT DEFAULT 'none',
        expires_at TEXT,
        joined_at  TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER,
        username     TEXT,
        full_name    TEXT,
        plan         TEXT,
        method       TEXT,
        photo_id     TEXT,
        hash_id      TEXT,
        status       TEXT DEFAULT 'pending',
        requested_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS records (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        term         TEXT UNIQUE,
        number       TEXT,
        country      TEXT,
        country_code TEXT,
        added_at     TEXT
    )""")
    conn.commit()
    conn.close()

def upsert_user(uid, username, full_name):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""INSERT INTO users (user_id,username,full_name,joined_at)
                 VALUES(?,?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, full_name=excluded.full_name""",
              (uid, username or "N/A", full_name, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()

def get_user(uid):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = c.fetchone(); conn.close(); return row

def approve_user(uid, plan):
    days    = PLANS[plan]["days"]
    expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status='approved',plan=?,expires_at=? WHERE user_id=?",
              (plan, expires, uid))
    conn.commit(); conn.close()

def reject_user(uid):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status='rejected' WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def revoke_user(uid):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("UPDATE users SET status='free',plan='none',expires_at=NULL WHERE user_id=?", (uid,))
    conn.commit(); conn.close()

def is_premium(uid):
    row = get_user(uid)
    if not row or row[3] != "approved": return False
    if row[5]:
        try:
            if datetime.now() > datetime.strptime(row[5], "%Y-%m-%d %H:%M"):
                revoke_user(uid); return False
        except: pass
    return True

def save_payment(uid, username, full_name, plan, method, photo_id, hash_id=""):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""INSERT INTO payments(user_id,username,full_name,plan,method,photo_id,hash_id,requested_at)
                 VALUES(?,?,?,?,?,?,?,?)""",
              (uid, username or "N/A", full_name, plan, method, photo_id, hash_id,
               datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()

def get_all_users():
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY joined_at DESC")
    rows = c.fetchall(); conn.close(); return rows

def save_record(term, number, country, cc):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO records(term,number,country,country_code,added_at)
                 VALUES(?,?,?,?,?)""",
              (str(term), number, country, cc, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit(); conn.close()

def get_record(term):
    conn = sqlite3.connect("bot_data.db")
    c = conn.cursor()
    c.execute("SELECT * FROM records WHERE term=?", (str(term),))
    row = c.fetchone(); conn.close(); return row

# ╔══════════════════════════════════════════════════════════════╗
# ║                  🌐  ZEPHREX API                            ║
# ╚══════════════════════════════════════════════════════════════╝
def fetch_api(term):
    try:
        r = requests.get("https://www.zephrexdigital.site/api",
                         params={"key": ZEPH_API_KEY, "type": "TG_NUM", "term": term},
                         timeout=10)
        d = r.json()
        if d.get("status"):
            return {
                "number"      : d["data"].get("number","N/A"),
                "country"     : d["data"].get("country","N/A"),
                "country_code": d["data"].get("country_code","N/A"),
            }
    except Exception as e:
        logging.error(f"API: {e}")
    return None

# ╔══════════════════════════════════════════════════════════════╗
# ║                  🎨  KEYBOARDS                              ║
# ╚══════════════════════════════════════════════════════════════╝
def kb_main():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
        InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
    ]])

def kb_plans():
    btns = [[InlineKeyboardButton(
                f"{p['label']}  ·  {p['price_inr']} / {p['price_usd']}",
                callback_data=f"plan_{k}"
             )] for k, p in PLANS.items()]
    btns.append([
        InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
        InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
    ])
    return InlineKeyboardMarkup(btns)

def kb_payment_method():
    """UPI ya Crypto method chunne ka keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 UPI / GPay / PhonePe", callback_data="method_upi")],
        [InlineKeyboardButton("₿ Bitcoin (BTC)",          callback_data="method_btc")],
        [InlineKeyboardButton("💎 Ethereum (ETH)",        callback_data="method_eth")],
        [InlineKeyboardButton("💵 USDT TRC20 (Tron)",     callback_data="method_usdt_trc20")],
        [InlineKeyboardButton("💵 USDT ERC20 (ETH)",      callback_data="method_usdt_erc20")],
        [InlineKeyboardButton("🔵 TON Coin",              callback_data="method_ton")],
        [InlineKeyboardButton("❌ Cancel",                callback_data="cancel_payment")],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_payment")
    ]])

def kb_owner_verify(uid, plan, method):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ APPROVE — {PLANS[plan]['label']}",
                              callback_data=f"approve_{uid}_{plan}")],
        [InlineKeyboardButton("❌ REJECT (Fake/Wrong)",
                              callback_data=f"reject_{uid}")],
        [InlineKeyboardButton("👑 Owner Panel", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}")]
    ])

# ╔══════════════════════════════════════════════════════════════╗
# ║                  🤖  HANDLERS                               ║
# ╚══════════════════════════════════════════════════════════════╝

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username, u.full_name)

    if is_premium(u.id):
        row = get_user(u.id)
        await update.message.reply_text(
            f"✨ *Welcome Back, {u.first_name}!*\n\n"
            f"🏆 Plan    : `{row[4].upper()}`\n"
            f"⏳ Expires : `{row[5]}`\n\n"
            f"📌 *Commands:*\n"
            f"🔍 `/lookup <id/username>`\n"
            f"➕ `/add <id/username>`\n"
            f"📊 `/status`",
            parse_mode="Markdown", reply_markup=kb_main()
        )
    else:
        await update.message.reply_text(
            f"👋 *Namaste {u.first_name}!*\n\n"
            f"🔒 Ye bot *Premium* hai.\n\n"
            f"💎 *Plans:*\n"
            f"┣ 🆓 1 Din Trial  → FREE\n"
            f"┣ 📅 7 Din        → ₹49  / $0.60\n"
            f"┣ 📆 30 Din       → ₹149 / $1.80\n"
            f"┗ ♾️ Lifetime     → ₹499 / $6.00\n\n"
            f"💳 *UPI, GPay, PhonePe*\n"
            f"🪙 *Crypto: BTC, ETH, USDT, TON*\n\n"
            f"👇 Plan chunke subscribe karo!",
            parse_mode="Markdown", reply_markup=kb_plans()
        )

async def status_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u   = update.effective_user
    row = get_user(u.id)
    if not row:
        await update.message.reply_text("❌ Pehle /start karo."); return
    em = {"approved":"✅","free":"🔓","rejected":"❌","revoked":"🚫"}.get(row[3],"❓")
    await update.message.reply_text(
        f"📊 *Aapka Status*\n\n"
        f"👤 Naam    : {row[2]}\n"
        f"🆔 ID      : `{row[0]}`\n"
        f"📌 Status  : {em} `{row[3].upper()}`\n"
        f"🏆 Plan    : `{row[4].upper()}`\n"
        f"⏳ Expires : `{row[5] or 'N/A'}`\n"
        f"📅 Joined  : `{row[6]}`",
        parse_mode="Markdown", reply_markup=kb_main()
    )

# ── Step 1: Plan chunna ──────────────────────────────────────
async def plan_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan = query.data.replace("plan_","")
    if plan not in PLANS: return

    p = PLANS[plan]
    ctx.user_data["chosen_plan"] = plan

    # Free trial → seedha method skip, screenshot manga
    if p["amount"] == 0:
        ctx.user_data["chosen_method"] = "free_trial"
        await query.edit_message_text(
            f"🆓 *Free Trial*\n\n"
            f"Koi payment nahi! Sirf 'OK' type karo\n"
            f"ya apna ek screenshot bhejo.\n\n"
            f"⏳ Owner approve karega jald hi!",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )
        return WAITING_SS

    # Paid → Payment method choose karo
    await query.edit_message_text(
        f"🏆 *{p['label']}* chunli!\n\n"
        f"💰 *Amount:*\n"
        f"┣ INR : *{p['price_inr']}*\n"
        f"┗ USD : *{p['price_usd']}*\n\n"
        f"👇 *Payment method chuno:*",
        parse_mode="Markdown", reply_markup=kb_payment_method()
    )
    return WAITING_METHOD

# ── Step 2: Method chunna ────────────────────────────────────
async def method_chosen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("method_","")
    plan   = ctx.user_data.get("chosen_plan")

    if not plan:
        await query.edit_message_text("❌ Session khatam. /start karo.")
        return ConversationHandler.END

    ctx.user_data["chosen_method"] = method
    p = PLANS[plan]

    # ── UPI ──
    if method == "upi":
        await query.edit_message_text(
            f"💳 *UPI Payment Details*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan    : *{p['label']}*\n"
            f"💰 Amount  : *{p['price_inr']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📲 *In mein se kisi bhi app se bhejo:*\n\n"
            f"┣ 🏦 UPI ID    : `{UPI_ID}`\n"
            f"┣ 📱 GPay/PP   : `{GPAY_NUM}`\n"
            f"┗ 👤 Name      : `{UPI_NAME}`\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📸 *Payment ke baad screenshot bhejo!*\n"
            f"⚠️ Fake screenshot = *permanent ban*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    # ── BTC ──
    elif method == "btc":
        await query.edit_message_text(
            f"₿ *Bitcoin (BTC) Payment*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan     : *{p['label']}*\n"
            f"💰 Amount   : *{p['price_usd']}* worth of BTC\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📬 *BTC Wallet Address:*\n"
            f"`{WALLETS['btc']}`\n\n"
            f"⚠️ *Sirf Bitcoin Network use karo!*\n\n"
            f"📸 *Transaction screenshot bhejo!*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    # ── ETH ──
    elif method == "eth":
        await query.edit_message_text(
            f"💎 *Ethereum (ETH) Payment*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan     : *{p['label']}*\n"
            f"💰 Amount   : *{p['price_usd']}* worth of ETH\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📬 *ETH Wallet Address:*\n"
            f"`{WALLETS['eth']}`\n\n"
            f"⚠️ *Sirf Ethereum Network (ERC20) use karo!*\n\n"
            f"📸 *Transaction screenshot bhejo!*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    # ── USDT TRC20 ──
    elif method == "usdt_trc20":
        await query.edit_message_text(
            f"💵 *USDT TRC20 (Tron) Payment*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan     : *{p['label']}*\n"
            f"💰 Amount   : *{p['price_usd']} USDT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📬 *USDT TRC20 Address (Tron):*\n"
            f"`{WALLETS['usdt_trc20']}`\n\n"
            f"⚠️ *Sirf TRC20 Network use karo!*\n"
            f"_(ERC20 se mat bhejo — coins kho jayenge!)_\n\n"
            f"📸 *Transaction screenshot bhejo!*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    # ── USDT ERC20 ──
    elif method == "usdt_erc20":
        await query.edit_message_text(
            f"💵 *USDT ERC20 (Ethereum) Payment*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan     : *{p['label']}*\n"
            f"💰 Amount   : *{p['price_usd']} USDT*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📬 *USDT ERC20 Address (Ethereum):*\n"
            f"`{WALLETS['usdt_erc20']}`\n\n"
            f"⚠️ *Sirf ERC20 Network use karo!*\n"
            f"_(TRC20 se mat bhejo — coins kho jayenge!)_\n\n"
            f"📸 *Transaction screenshot bhejo!*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    # ── TON ──
    elif method == "ton":
        await query.edit_message_text(
            f"🔵 *TON Coin Payment*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 Plan     : *{p['label']}*\n"
            f"💰 Amount   : *{p['price_usd']}* worth of TON\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📬 *TON Wallet Address:*\n"
            f"`{WALLETS['ton']}`\n\n"
            f"💡 *Telegram Wallet se bhi bhej sakte ho!*\n\n"
            f"📸 *Transaction screenshot bhejo!*",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    return WAITING_SS

# ── Step 3: Screenshot aaya ──────────────────────────────────
async def screenshot_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u      = update.effective_user
    plan   = ctx.user_data.get("chosen_plan")
    method = ctx.user_data.get("chosen_method","unknown")

    if not plan:
        await update.message.reply_text("❌ Session khatam. /start karke dobara try karo.")
        return ConversationHandler.END

    p = PLANS[plan]

    # Photo ya text dono accept
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif update.message.text:
        photo_id = "TEXT_ONLY"
    else:
        await update.message.reply_text("📸 Screenshot ya message bhejo!")
        return WAITING_SS

    save_payment(u.id, u.username, u.full_name, plan, method, photo_id)

    # Method ka display naam
    method_labels = {
        "upi"        : "💳 UPI/GPay",
        "btc"        : "₿ Bitcoin",
        "eth"        : "💎 Ethereum",
        "usdt_trc20" : "💵 USDT TRC20",
        "usdt_erc20" : "💵 USDT ERC20",
        "ton"        : "🔵 TON Coin",
        "free_trial" : "🆓 Free Trial",
    }
    method_name = method_labels.get(method, method)

    # User ko confirmation
    await update.message.reply_text(
        f"✅ *Payment Request Bhej Di!*\n\n"
        f"🏆 Plan    : *{p['label']}*\n"
        f"💰 Amount  : *{p['price_inr']} / {p['price_usd']}*\n"
        f"💳 Method  : *{method_name}*\n"
        f"⏳ Status  : *Pending Verification*\n\n"
        f"_Owner verify karega jald hi! 🙏_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("👑 Owner", url=f"https://t.me/{OWNER_USERNAME.replace('@','')}"),
            InlineKeyboardButton(CHANNEL_NAME, url=CHANNEL_LINK),
        ]])
    )

    # ── Owner ko notify + screenshot forward ──
    owner_caption = (
        f"💰 *NAYA PAYMENT REQUEST!*\n\n"
        f"{'━'*25}\n"
        f"👤 Name    : {u.full_name}\n"
        f"🆔 ID      : `{u.id}`\n"
        f"📌 User    : @{u.username or 'N/A'}\n"
        f"{'━'*25}\n"
        f"🏆 Plan    : *{p['label']}*\n"
        f"💰 Amount  : *{p['price_inr']} / {p['price_usd']}*\n"
        f"💳 Method  : *{method_name}*\n"
        f"🕐 Time    : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'━'*25}\n\n"
        f"👇 *Verify karke Approve/Reject karo:*"
    )

    try:
        if photo_id != "TEXT_ONLY":
            await ctx.bot.send_photo(
                chat_id=OWNER_ID,
                photo=photo_id,
                caption=owner_caption,
                parse_mode="Markdown",
                reply_markup=kb_owner_verify(u.id, plan, method)
            )
        else:
            await ctx.bot.send_message(
                chat_id=OWNER_ID,
                text=owner_caption + "\n\n_(Screenshot nahi aaya)_",
                parse_mode="Markdown",
                reply_markup=kb_owner_verify(u.id, plan, method)
            )
    except Exception as e:
        logging.error(f"Owner notify: {e}")

    ctx.user_data.clear()
    return ConversationHandler.END

# ── Cancel ───────────────────────────────────────────────────
async def cancel_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.edit_message_text(
        "❌ *Payment cancel ho gayi.*\n\n/start karke dobara try karo.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ── Owner: Approve / Reject ───────────────────────────────────
async def approve_reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != OWNER_ID:
        await query.answer("🚫 Sirf Owner!", show_alert=True); return

    data = query.data

    if data.startswith("approve_"):
        parts = data.split("_")
        uid   = int(parts[1])
        plan  = parts[2]
        approve_user(uid, plan)
        p = PLANS[plan]

        new_text = (query.message.caption or query.message.text or "") + f"\n\n✅ *APPROVED — {p['label']}*"
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text, parse_mode="Markdown")
            else:
                await query.edit_message_text(new_text, parse_mode="Markdown")
        except: pass

        try:
            row = get_user(uid)
            await ctx.bot.send_message(
                uid,
                f"🎉 *Congratulations!*\n\n"
                f"✅ Payment *verify* ho gaya!\n\n"
                f"🏆 Plan    : *{p['label']}*\n"
                f"⏳ Expires : *{row[5]}*\n\n"
                f"🔍 Ab `/lookup` ya `/add` use karo! 🚀",
                parse_mode="Markdown", reply_markup=kb_main()
            )
        except Exception as e:
            logging.error(f"Approve notify: {e}")

    elif data.startswith("reject_"):
        uid = int(data.replace("reject_",""))
        reject_user(uid)

        new_text = (query.message.caption or query.message.text or "") + "\n\n❌ *REJECTED*"
        try:
            if query.message.photo:
                await query.edit_message_caption(caption=new_text, parse_mode="Markdown")
            else:
                await query.edit_message_text(new_text, parse_mode="Markdown")
        except: pass

        try:
            await ctx.bot.send_message(
                uid,
                f"❌ *Payment Reject Ho Gayi!*\n\n"
                f"Reason: Screenshot fake ya wrong amount.\n\n"
                f"Sahi payment karo ya Owner se contact karo:\n"
                f"👑 {OWNER_USERNAME}",
                parse_mode="Markdown", reply_markup=kb_plans()
            )
        except: pass

# ── Premium Commands ──────────────────────────────────────────
async def lookup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_premium(u.id):
        await update.message.reply_text(
            f"🔒 *Premium feature hai!*\n\n{OWNER_USERNAME} se subscribe karo 👇",
            parse_mode="Markdown", reply_markup=kb_plans()); return

    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/lookup <user_id ya username>`", parse_mode="Markdown"); return

    term = ctx.args[0].replace("@","").strip()
    msg  = await update.message.reply_text(f"🔍 `{term}` dhundh raha hoon...", parse_mode="Markdown")

    row = get_record(term)
    if row:
        await msg.edit_text(
            f"✅ *Record Mila! (DB)*\n\n"
            f"🆔 Term    : `{row[1]}`\n"
            f"📱 Number  : `{row[2]}`\n"
            f"🌍 Country : {row[3]}\n"
            f"📞 Code    : {row[4]}\n"
            f"🕐 Added   : {row[5]}",
            parse_mode="Markdown", reply_markup=kb_main()); return

    result = fetch_api(term)
    if result:
        save_record(term, result["number"], result["country"], result["country_code"])
        await msg.edit_text(
            f"✅ *Number Mila!*\n\n"
            f"🆔 Term    : `{term}`\n"
            f"📱 Number  : `{result['number']}`\n"
            f"🌍 Country : {result['country']}\n"
            f"📞 Code    : {result['country_code']}\n"
            f"💾 _Saved!_",
            parse_mode="Markdown", reply_markup=kb_main())
    else:
        await msg.edit_text(f"❌ `{term}` ka data nahi mila.", parse_mode="Markdown")

async def add_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if not is_premium(u.id):
        await update.message.reply_text("🔒 *Premium feature!*", parse_mode="Markdown", reply_markup=kb_plans()); return
    if not ctx.args:
        await update.message.reply_text("⚠️ Usage: `/add <user_id ya username>`", parse_mode="Markdown"); return

    term = ctx.args[0].replace("@","").strip()
    msg  = await update.message.reply_text(f"⏳ Fetch kar raha hoon `{term}`...", parse_mode="Markdown")
    result = fetch_api(term)
    if result:
        save_record(term, result["number"], result["country"], result["country_code"])
        await msg.edit_text(
            f"✅ *Saved!*\n\n🆔 `{term}` → 📱 `{result['number']}` | {result['country']} {result['country_code']}",
            parse_mode="Markdown", reply_markup=kb_main())
    else:
        await msg.edit_text(f"❌ Data nahi mila `{term}` ke liye.", parse_mode="Markdown")

# ── Admin Commands ────────────────────────────────────────────
async def admin_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("🚫 Sirf Owner!"); return
    rows     = get_all_users()
    approved = sum(1 for r in rows if r[3]=="approved")
    free     = sum(1 for r in rows if r[3]=="free")
    text = f"👥 *Total: {len(rows)}* | ✅ {approved} Active | 🔓 {free} Free\n\n"
    for r in rows[:20]:
        em = {"approved":"✅","free":"🔓","rejected":"❌","revoked":"🚫"}.get(r[3],"❓")
        text += f"{em} `{r[0]}` @{r[1]} | {r[4]} | {r[5] or 'N/A'}\n"
    if len(rows) > 20: text += f"\n_...{len(rows)-20} aur hain_"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb_main())

async def admin_approve_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if len(ctx.args) < 2:
        await update.message.reply_text("⚠️ `/approve <user_id> <plan>`\nPlans: trial/weekly/monthly/lifetime", parse_mode="Markdown"); return
    uid  = int(ctx.args[0])
    plan = ctx.args[1].lower()
    if plan not in PLANS:
        await update.message.reply_text("❌ Plan galat! Use: trial/weekly/monthly/lifetime"); return
    approve_user(uid, plan)
    await update.message.reply_text(f"✅ `{uid}` → *{PLANS[plan]['label']}* approved!", parse_mode="Markdown")
    try:
        row = get_user(uid)
        await ctx.bot.send_message(uid,
            f"🎉 *Access Approved!*\n🏆 Plan: *{PLANS[plan]['label']}*\n⏳ Expires: *{row[5]}*",
            parse_mode="Markdown", reply_markup=kb_main())
    except: pass

async def admin_revoke_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not ctx.args:
        await update.message.reply_text("⚠️ `/revoke <user_id>`", parse_mode="Markdown"); return
    uid = int(ctx.args[0])
    revoke_user(uid)
    await update.message.reply_text(f"🚫 `{uid}` revoked!", parse_mode="Markdown")
    try:
        await ctx.bot.send_message(uid, "🚫 Aapka access revoke ho gaya.\nOwner se contact karo.", reply_markup=kb_plans())
    except: pass

async def broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if not ctx.args:
        await update.message.reply_text("⚠️ `/broadcast <message>`", parse_mode="Markdown"); return
    msg_text = " ".join(ctx.args)
    rows = get_all_users(); sent = 0
    for r in rows:
        try:
            await ctx.bot.send_message(r[0], f"📢 *Owner Message:*\n\n{msg_text}", parse_mode="Markdown", reply_markup=kb_main())
            sent += 1
        except: pass
    await update.message.reply_text(f"✅ {sent}/{len(rows)} ko bheja!")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    text = update.message.text.strip().replace("@","")
    if not is_premium(u.id):
        await update.message.reply_text(
            f"🔒 *Premium Bot!*\n\n{OWNER_USERNAME} se subscribe karo 👇",
            parse_mode="Markdown", reply_markup=kb_plans()); return
    row = get_record(text)
    if row:
        await update.message.reply_text(
            f"✅ `{row[1]}` → 📱 `{row[2]}` | {row[3]} {row[4]}",
            parse_mode="Markdown", reply_markup=kb_main()); return
    result = fetch_api(text)
    if result:
        save_record(text, result["number"], result["country"], result["country_code"])
        await update.message.reply_text(
            f"✅ `{text}` → 📱 `{result['number']}` | {result['country']} {result['country_code']}",
            parse_mode="Markdown", reply_markup=kb_main())
    else:
        await update.message.reply_text(f"❌ `{text}` ka data nahi mila.", parse_mode="Markdown")

# ╔══════════════════════════════════════════════════════════════╗
# ║                     🚀  MAIN                                ║
# ╚══════════════════════════════════════════════════════════════╝
def main():
    init_db()
    print("🤖 Premium Bot Start!")
    print(f"👑 Owner  : {OWNER_ID}")
    print(f"💳 UPI    : {UPI_ID}")
    print(f"₿  BTC    : {WALLETS['btc'][:20]}...")

    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler: Plan → Method → Screenshot
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(plan_chosen, pattern="^plan_")],
        states={
            WAITING_METHOD: [
                CallbackQueryHandler(method_chosen,  pattern="^method_"),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$"),
            ],
            WAITING_SS: [
                MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, screenshot_received),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$"),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$")],
        per_user=True, per_chat=True
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("status",    status_cmd))
    app.add_handler(CommandHandler("lookup",    lookup))
    app.add_handler(CommandHandler("add",       add_cmd))
    app.add_handler(CommandHandler("users",     admin_users))
    app.add_handler(CommandHandler("approve",   admin_approve_cmd))
    app.add_handler(CommandHandler("revoke",    admin_revoke_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(approve_reject, pattern="^(approve|reject)_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()
