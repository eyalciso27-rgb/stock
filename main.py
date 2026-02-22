import os
import sqlite3
import pandas as pd
import pytz  # ספרייה לניהול אזורי זמן
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# נתיב חיצוני מבודד ב-Railway
DB_PATH = '/database/stocks.db'

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT)''')
    c.execute("SELECT COUNT(*) FROM stocks")
    if c.fetchone()[0] == 0:
        default_stocks = [
            ('נאסד"ק 100', '^NDX'), ('S&P 500', '^GSPC'),
            ('ביטקוין', 'BTC-USD'), ('דולר/שקל', 'USDILS=X'),
            ('מדד תא 35', 'TA35.TA')
        ]
        c.executemany("INSERT INTO stocks (name, ticker) VALUES (?, ?)", default_stocks)
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['📊 הצג את כל השערים'],
        ['➕ הוספת מניה', '❌ הסרת מניה'],
        ['❓ עזרה']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"שלום {update.effective_user.first_name}! 👋\nהבוט מוכן עם שעון ישראל מעודכן.",
        reply_markup=reply_markup
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("מרענן נתונים... 🔄")
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks")
        rows = c.fetchall()
        conn.close()

        if not rows:
            await status_msg.edit_text("הרשימה ריקה.")
            return

        tickers_list = [row[1] for row in rows]
        ticker_names = {row[1]: row[0] for row in rows}
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        all_data = t.price
        
        msg = "📊 **שערי מניות ומדדים:**\n━━━━━━━━━━━━━━━\n"
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            name = ticker_names.get(ticker)
            if not isinstance(data, dict):
                msg += f"🔹 **{name}**\n`שגיאה בסימול ({ticker})`\n\n"
                continue
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
                if "^" in ticker: curr = "" 
                msg += f"🔹 **{name}**\n`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        # חישוב זמן ישראל
        israel_tz = pytz.timezone('Asia/Jerusalem')
        current_time = pd.Timestamp.now(tz=israel_tz).strftime('%H:%M:%S')
        
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"⏰ זמן עדכון (ישראל): {current_time}"
        await status_msg.edit_text(msg, parse_mode='Markdown')
    except Exception as e:
        await status_msg.edit_text(f"שגיאה: {e}")

async def show_removal_menu(update: Update):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, ticker FROM stocks")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("אין מניות להסרה.")
        return

    keyboard = []
    for name, ticker in rows:
        keyboard.append([InlineKeyboardButton(f"❌ הסר את {name} ({ticker})", callback_data=f"del_{ticker}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("בחר מניה להסרה מהרשימה:", reply_markup=reply_markup)

async def remove_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ticker_to_remove = query.data.replace("del_", "")
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ?", (ticker_to_remove,))
    conn.commit()
    conn.close()
    
    await query.edit_message_text(text=f"✅ הסימול **{ticker_to_remove}** הוסר בהצלחה.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 הצג את כל השערים':
        await all_prices(update, context)
    elif text == '❌ הסרת מניה':
        await show_removal_menu(update)
    elif text == '➕ הוספת מניה':
        await update.message.reply_text("להוספה שלח: `/add [סימול] [שם]`\nדוגמה: `/add AAPL אפל`", parse_mode='Markdown')
    elif text == '❓ עזרה':
        await start(update, context)

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker) VALUES (?, ?)", (name, ticker))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ המניה **{name}** נוספה.")

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CallbackQueryHandler(remove_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    app.run_polling()

if __name__ == "__main__":
    main()
