import os
import sqlite3
import pandas as pd
import pytz
import asyncio
import logging
from datetime import datetime
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# לוגים לזיהוי תקלות
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- הגדרות מערכת ---
DB_PATH = '/database/personal_stocks.db'
ADMIN_ID = 7969303152 
DEFAULT_LIMIT = 10
PREMIUM_LIMIT = 50

def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir): os.makedirs(db_dir, mode=0o777, exist_ok=True)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT, user_id INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT, is_premium INTEGER DEFAULT 0)')
        try: c.execute('ALTER TABLE stocks ADD COLUMN quantity REAL DEFAULT 0')
        except: pass
        try: c.execute('ALTER TABLE stocks ADD COLUMN purchase_price REAL DEFAULT 0')
        except: pass
        conn.commit(); conn.close()
    except Exception as e: logging.error(f"DB Error: {e}")

def register_user(user_id, first_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user_id, first_name))
        c.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        conn.commit(); conn.close()
    except: pass

def get_greeting():
    # קביעת ברכה לפי שעה בישראל
    israel_tz = pytz.timezone('Asia/Jerusalem')
    hour = datetime.now(israel_tz).hour
    if 5 <= hour < 12: return "בוקר טוב ☀️"
    if 12 <= hour < 18: return "צהריים טובים ✨"
    if 18 <= hour < 22: return "ערב טוב 🌙"
    return "לילה טוב 😴"

# --- לוגיקת נתונים ---

async def get_stock_analysis(ticker_symbol):
    try:
        # בביטקוין וקריפטו ננסה למשוך חדשות בפורמט מעט שונה
        t = Ticker(ticker_symbol)
        news_data = t.news(5)
        
        analysis = f"🧐 **חדשות עבור {ticker_symbol}:**\n\n"
        if not news_data or not isinstance(news_data, list):
            return f"⚠️ לא נמצאו חדשות עדכניות עבור {ticker_symbol} ב-Yahoo Finance. ייתכן שהמקור חסום זמנית."

        for item in news_data[:3]:
            title = item.get('title', 'ללא כותרת')
            link = item.get('link', '#')
            analysis += f"• [{title}]({link})\n\n"
        return analysis
    except: return f"⚠️ כרגע יש עומס ב-Yahoo Finance. נסה שוב בעוד דקה."

async def get_prices_text(user_id, user_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker, quantity, purchase_price FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: return f"{get_greeting()} {user_name},\nהתיק שלך ריק כרגע.", None
        
        t = Ticker([r[1] for r in rows], asynchronous=True, formatted=False)
        prices = t.price
        
        msg = f"{get_greeting()} **{user_name}**, הנה התיק שלך:\n━━━━━━━━━━━━━━━\n\n"
        keyboard = []
        for name, ticker, qty, buy_p in rows:
            d = prices.get(ticker, {})
            curr_p = d.get('regularMarketPrice', 0)
            change = d.get('regularMarketChangePercent', 0) * 100
            icon = "🟢" if change >= 0 else "🔴"
            symbol = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
            
            msg += f"🔹 **{name}** ({ticker})\nשער: `{symbol}{curr_p:,.2f}` ({icon} {change:+.2f}%)\n"
            if qty > 0 and buy_p > 0:
                p_pct = ((curr_p / buy_p) - 1) * 100
                msg += f"💰 רווח כולל: `{p_pct:+.2f}%`\n"
            msg += "\n"
            keyboard.append([InlineKeyboardButton(f"🔍 ניתוח: {name}", callback_data=f"analyze_{ticker}")])

        keyboard.append([InlineKeyboardButton("🔄 רענון נתונים", callback_data="refresh")])
        return msg, InlineKeyboardMarkup(keyboard)
    except: return "⚠️ שגיאה בטעינת נתונים.", None

# --- הנדלרים ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text
    state = context.user_data.get('state')
    register_user(user_id, user_name)

    main_kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user_id == ADMIN_ID: main_kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])

    if text == '📊 הצג את כל השערים':
        msg, kb = await get_prices_text(user_id, user_name)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
    
    elif text == '➕ הוספת מניה':
        await update.message.reply_text("סימול המניה (למשל AAPL):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'T'
    
    # ... (לוגיקת הוספה/הסרה/ניהול כפי שהייתה) ...
    # לקיצור, הקפד להשאיר את ה-states שכתבנו בגרסה הקודמת

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.first_name)
    kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user.id == ADMIN_ID: kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])
    
    welcome = f"{get_greeting()} **{user.first_name}**!\nברוך הבא לבוט המניות האישי שלך."
    await update.message.reply_text(welcome, parse_mode='Markdown', reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name

    if query.data.startswith("analyze_"):
        ticker = query.data.split("_")[1]
        analysis = await get_stock_analysis(ticker)
        await context.bot.send_message(chat_id=user_id, text=analysis, parse_mode='Markdown', disable_web_page_preview=True)
    elif query.data == "refresh":
        msg, kb = await get_prices_text(user_id, user_name)
        try: await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
        except: pass
    # ... (המשך ה-callback של del ו-tgp)

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
