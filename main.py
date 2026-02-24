import os
import sqlite3
import pandas as pd
import pytz
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# שימוש בווליום הקיים עם קובץ חדש להפרדה בטוחה
DB_PATH = '/database/personal_stocks.db'

# רשימת ברירת המחדל לכל משתמש חדש
DEFAULT_LIST = [
    ('נאסד"ק 100', '^NDX'), 
    ('מדד S&P 500', 'SPY'),
    ('ביטקוין', 'BTC-USD'), 
    ('דולר/שקל', 'USDILS=X'),
    ('מדד תא 35', 'TA35.TA')
]

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # יצירת טבלה הכוללת user_id לניהול אישי לכל משתמש
    c.execute('''CREATE TABLE IF NOT EXISTS stocks 
                 (name TEXT, ticker TEXT, user_id INTEGER)''')
    conn.commit()
    conn.close()

def get_greeting():
    israel_tz = pytz.timezone('Asia/Jerusalem')
    hour = pd.Timestamp.now(tz=israel_tz).hour
    if 5 <= hour < 12: return "בוקר טוב"
    elif 12 <= hour < 18: return "צהריים טובים"
    elif 18 <= hour < 22: return "ערב טוב"
    else: return "לילה טוב"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    greeting = get_greeting()
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
    
    # אם המשתמש חדש, הבוט מעתיק עבורו את רשימת ברירת המחדל
    if c.fetchone()[0] == 0:
        for name, ticker in DEFAULT_LIST:
            c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, user_id))
        conn.commit()
    conn.close()

    keyboard = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה'], ['❓ עזרה']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"{greeting}, {user_name}! 👋\nהמערכת האישית שלך הופעלה. בתור התחלה, טענתי עבורך את המניות המוכרות.",
        reply_markup=reply_markup
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    greeting = get_greeting()
    status_msg = await update.message.reply_text(f"מחלץ נתונים עבורך, {user_name}... 🔄")
    
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()

        if not rows:
            await status_msg.edit_text("הרשימה האישית שלך ריקה. השתמש ב-➕ הוספת מניה."); return

        tickers_list = [row[1] for row in rows]
        ticker_names = {row[1]: row[0] for row in rows}
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        all_data = t.price
        
        msg = f"{greeting}, {user_name}! 📊\n**אלו השערים האישיים שלך:**\n━━━━━━━━━━━━━━━\n\n"
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            name = ticker_names.get(ticker)
            if not isinstance(data, dict):
                msg += f"🔹 **{name}**\n`שגיאה בסימול ({ticker})`\n\n"; continue
            
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
                if "^" in ticker: curr = "" 
                msg += f"🔹 **{name}**\n`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        israel_tz = pytz.timezone('Asia/Jerusalem')
        current_time = pd.Timestamp.now(tz=israel_tz).strftime('%H:%M:%S')
        msg += "━━━━━━━━━━━━━━━\n" + f"⏰ זמן עדכון: {current_time}"
        await status_msg.edit_text(msg, parse_mode='Markdown')
    except Exception as e:
        await status_msg.edit_text(f"שגיאה: {e}")

async def show_removal_menu(update: Update):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
    rows = c.fetchall(); conn.close()

    if not rows:
        await update.message.reply_text("אין מניות להסרה מהתיק שלך."); return

    keyboard = [[InlineKeyboardButton(f"❌ הסר את {n}", callback_data=f"del_{t}")] for n, t in rows]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("בחר מניה להסרה מהרשימה האישית שלך:", reply_markup=reply_markup)

async def remove_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()
    ticker_to_remove = query.data.replace("del_", "")
    
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ? AND user_id = ?", (ticker_to_remove, user_id))
    conn.commit(); conn.close()
    await query.edit_message_text(text=f"✅ המניה **{ticker_to_remove}** הוסרה מהתיק האישי שלך.")

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2: return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, user_id))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ המניה **{name}** נוספה לרשימה האישית שלך.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 הצג את כל השערים': await all_prices(update, context)
    elif text == '❌ הסרת מניה': await show_removal_menu(update)
    elif text == '➕ הוספת מניה': await update.message.reply_text("להוספה: `/add [סימול] [שם]`", parse_mode='Markdown')
    elif text == '❓ עזרה': await start(update, context)

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
