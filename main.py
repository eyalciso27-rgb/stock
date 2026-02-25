import os
import sqlite3
import pandas as pd
import pytz
import asyncio
import logging
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
        # יצירת התיקייה אם היא לא קיימת עם הרשאות מתאימות
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, mode=0o777, exist_ok=True)
            logging.info(f"Created directory: {db_dir}")
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT, user_id INTEGER, quantity REAL DEFAULT 0, purchase_price REAL DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT, is_premium INTEGER DEFAULT 0)')
        try:
            c.execute('ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0')
        except: pass
        conn.commit()
        conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Database Init Error: {e}")
        raise

def register_user(user_id, first_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user_id, first_name))
        conn.commit(); conn.close()
    except Exception as e: logging.error(f"Register User Error: {e}")

def get_user_limit(user_id):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))
        res = c.fetchone(); conn.close()
        return PREMIUM_LIMIT if res and res[0] == 1 else DEFAULT_LIMIT
    except: return DEFAULT_LIMIT

# --- לוגיקת נתונים ---

async def get_stock_analysis(ticker_symbol):
    try:
        t = Ticker(ticker_symbol)
        news = t.news(3)
        if not news: return "לא נמצאו חדשות עדכניות."
        msg = f"🧐 **ניתוח עבור {ticker_symbol}:**\n\n"
        for item in news:
            msg += f"• [{item['title']}]({item['link']})\n"
        return msg
    except: return "⚠️ שגיאה בשליפת נתונים."

async def get_prices_text(user_id, user_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker, quantity, purchase_price FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: return "התיק שלך ריק.", None
        
        t = Ticker([r[1] for r in rows], asynchronous=True, formatted=False)
        prices = t.price
        
        msg = f"📊 **התיק של {user_name}:**\n━━━━━━━━━━━━━━━\n\n"
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
        keyboard.append([InlineKeyboardButton("🔄 רענון", callback_data="refresh")])
        return msg, InlineKeyboardMarkup(keyboard)
    except Exception as e: return f"⚠️ שגיאה: {e}", None

# --- הנדלרים ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get('state')
    register_user(user_id, update.effective_user.first_name)

    main_kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user_id == ADMIN_ID: main_kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])

    if text == '📊 הצג את כל השערים':
        msg, kb = await get_prices_text(user_id, update.effective_user.first_name)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
    
    elif text == '➕ הוספת מניה':
        limit = get_user_limit(user_id)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
        if c.fetchone()[0] >= limit:
            await update.message.reply_text(f"🚫 מגבלה של {limit} מניות.")
            return
        await update.message.reply_text("סימול (למשל AAPL):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'T'
    
    # ... (שאר לוגיקת ה-T/NAME/PRICE/QTY כפי שהייתה קודם) ...
    # לקיצור, כאן נכנסים ה-States של WAITING_TICKER וכו'

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update.effective_user.id, update.effective_user.first_name)
    kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if update.effective_user.id == ADMIN_ID: kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])
    await update.message.reply_text(f"שלום {update.effective_user.first_name}!", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    
    # פתרון ל-Conflict: ניקוי עדכונים ישנים בזמן החיבור
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(lambda u, c: None)) # זמני למניעת שגיאות קלבאק
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logging.info("Bot is starting...")
    app.run_polling(drop_pending_updates=True) # חשוב למניעת Conflict

if __name__ == "__main__": main()
