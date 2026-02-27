import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

# ================================
BOT_TOKEN    = "7870678989:AAEi4k5OrTnMD5Rcd1BWz4xLfMqlFUcgE7M"   # @BotFather se lena
ZEPH_API_KEY = "ZEPH-4O1YD"
# ================================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Namaste!\n\nUser ID bhejo → Number milega ✅"
    )

async def get_number(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text.strip()

    await update.message.reply_text("🔍 Dhundh raha hoon...")

    try:
        r = requests.get(
            "https://www.zephrexdigital.site/api",
            params={
                "key" : ZEPH_API_KEY,
                "type": "TG_NUM",
                "term": user_id
            },
            timeout=10
        )
        d = r.json()

        if d.get("status"):
            data = d["data"]
            await update.message.reply_text(
                f"✅ *Number Mila!*\n\n"
                f"🆔 ID      : `{user_id}`\n"
                f"📱 Number  : `{data['number']}`\n"
                f"🌍 Country : {data['country']}\n"
                f"📞 Code    : {data['country_code']}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Nahi mila! ID check karo.")

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

def main():
    print("🤖 Bot chal raha hai...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_number))
    app.run_polling()

if __name__ == "__main__":
    main()
