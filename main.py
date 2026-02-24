import os
import sqlite3
import pandas as pd
import pytz
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# נתיב הווליום הקיים
DB_PATH = '/database/personal_stocks.db'

# רשימת ברירת המחדל לכל משתמש (ID) חדש
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
    c.execute('''CREATE TABLE IF NOT EXISTS stocks 
                 (name TEXT, ticker TEXT, user_id INTEGER)''')
    conn.commit()
    conn.close()

# פונקציה שמוודא שלמשתמש יש את מניות ברירת המחדל
def ensure_default_stocks(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
    if c.fetchone()[0] == 0:
        for name, ticker in DEFAULT_LIST:
            c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, user_id))
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
    ensure_default_stocks(user_id) # מוודא שיש מניות ב-ID הזה
    
    keyboard = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה'], ['❓ עזרה']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"{get_greeting()}, {user_name}! 👋\nהמערכת האישית הופעלה עם מניות ברירת המחדל.",
        reply_markup=reply_markup
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    ensure_default_stocks(user_id) # בדיקה נוספת למקרה שהמשתמש לא הריץ /start
    
    status_msg = await update.message.reply_text(f"מעדכן נתונים עבורך, {user_name}... 🔄")
    
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()

        tickers_list = [row[1] for row in rows]
        ticker_names = {row[1]: row[0] for row in rows}
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        all_data = t.price
        
        msg = f"{get_greeting()}, {user_name}! 📊\n**אלו השערים האישיים שלך:**\n━━━━━━━━━━━━━━━\n\n"
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            name = ticker_names.get(ticker)
            if not isinstance(data, dict): continue
            
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
                if "^" in ticker: curr = "" 
                msg += f"🔹 **{name}**\n`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        current_time = pd.Timestamp.now(tz=pytz.timezone('Asia/Jerusalem')).strftime('%H:%M:%S')
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
        await update.message.reply_text("אין מניות להסרה."); return
    keyboard = [[InlineKeyboardButton(f"❌ {n}", callback_data=f"del_{t}")] for n, t in rows]
    await update.message.reply_text("בחר מניה להסרה:", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = update.effective_user.id
    ticker = query.data.replace("del_", "")
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ? AND user_id = ?", (ticker, user_id))
    conn.commit(); conn.close()
    await query.edit_message_text(text=f"✅ המניה {ticker} הוסרה מהתיק האישי שלך.")

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2: return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, user_id))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ המניה **{name}** נוספה.")

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
    app.add_handler(CommandHandler("start", start)); app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CallbackQueryHandler(remove_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__": main()
