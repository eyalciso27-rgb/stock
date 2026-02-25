import os
import sqlite3
import pandas as pd
import pytz
import asyncio
import logging
from datetime import datetime, timedelta
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# הגדרת לוגים לזיהוי תקלות ב-Railway
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- הגדרות מערכת ---
DB_PATH = '/database/personal_stocks.db'
ADMIN_ID = 7969303152 
DEFAULT_LIMIT = 10
PREMIUM_LIMIT = 50

# זיכרון זמני לחדשות
news_cache = {}

def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir): os.makedirs(db_dir, mode=0o777, exist_ok=True)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT, user_id INTEGER, quantity REAL DEFAULT 0, purchase_price REAL DEFAULT 0)')
        c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT, is_premium INTEGER DEFAULT 0)')
        try: c.execute('ALTER TABLE stocks ADD COLUMN quantity REAL DEFAULT 0')
        except: pass
        try: c.execute('ALTER TABLE stocks ADD COLUMN purchase_price REAL DEFAULT 0')
        except: pass
        try: c.execute('ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0')
        except: pass
        conn.commit(); conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e: logging.error(f"DB Error: {e}")

def get_greeting(first_name):
    israel_tz = pytz.timezone('Asia/Jerusalem')
    hour = datetime.now(israel_tz).hour
    if 5 <= hour < 12: greet = "בוקר טוב"
    elif 12 <= hour < 18: greet = "צהריים טובים"
    elif 18 <= hour < 22: greet = "ערב טוב"
    else: greet = "לילה טוב"
    return f"{greet}, {first_name}! 💎"

# --- לוגיקת נתונים ---

async def get_stock_analysis(ticker_symbol):
    now = datetime.now()
    if ticker_symbol in news_cache:
        cached_time, cached_data = news_cache[ticker_symbol]
        if now - cached_time < timedelta(minutes=15): return cached_data

    try:
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        t = Ticker(ticker_symbol, user_agent=ua)
        news_data = t.news(3)
        if not news_data or not isinstance(news_data, list): raise Exception("No news")
        
        analysis = f"🧐 **חדשות עבור {ticker_symbol}:**\n\n"
        for item in news_data:
            analysis += f"• [{item.get('title')}]({item.get('link')})\n\n"
        news_cache[ticker_symbol] = (now, analysis)
        return analysis
    except:
        inv_url = f"https://www.investing.com/search/?q={ticker_symbol.split('-')[0]}"
        return f"⚠️ Yahoo Finance חסום זמנית.\n\n[לחץ כאן לחדשות ב-Investing.com]({inv_url})"

async def get_prices_text(user_id, user_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker, quantity, purchase_price FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        greeting = get_greeting(user_name)
        if not rows: return f"{greeting}\n\nהתיק שלך ריק כרגע.", None
        
        t = Ticker([r[1] for r in rows], asynchronous=True, formatted=False)
        prices = t.price
        msg = f"{greeting}\nמצב התיק שלך:\n━━━━━━━━━━━━━━━\n\n"
        kb = []
        for name, ticker, qty, buy_p in rows:
            d = prices.get(ticker, {})
            curr_p = d.get('regularMarketPrice', 0)
            change = d.get('regularMarketChangePercent', 0) * 100
            icon = "🟢" if change >= 0 else "🔴"
            symbol = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
            msg += f"🔹 **{name}**\nשער: `{symbol}{curr_p:,.2f}` ({icon} {change:+.2f}%)\n\n"
            kb.append([InlineKeyboardButton(f"🔍 ניתוח: {name}", callback_data=f"analyze_{ticker}")])
        kb.append([InlineKeyboardButton("🔄 רענון נתונים", callback_data="refresh")])
        return msg, InlineKeyboardMarkup(kb)
    except: return "⚠️ שגיאה בטעינה.", None

# --- טיפול בהודעות ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    text = update.message.text
    state = context.user_data.get('state')

    # מקלדות
    admin_options = ['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם']
    main_kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user_id == ADMIN_ID: main_kb.append(admin_options)
    reply_markup = ReplyKeyboardMarkup(main_kb, resize_keyboard=True)

    # כפתורי ניהול
    if user_id == ADMIN_ID and text == '📊 סטטיסטיקה':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); u_cnt = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1"); p_cnt = c.fetchone()[0]
        await update.message.reply_text(f"👥 משתמשים: {u_cnt}\n💎 פרימיום: {p_cnt}")
        return
    elif user_id == ADMIN_ID and text == '💎 ניהול פרימיום':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id, first_name, is_premium FROM users WHERE user_id != ?", (ADMIN_ID,))
        users = c.fetchall(); conn.close()
        kb = [[InlineKeyboardButton(f"{'💎' if p else '👤'} {n}", callback_data=f"tgp_{uid}")] for uid, n, p in users]
        await update.message.reply_text("בחר משתמש לשינוי סטטוס:", reply_markup=InlineKeyboardMarkup(kb))
        return
    elif user_id == ADMIN_ID and text == '📢 הודעה לכולם':
        await update.message.reply_text("כתוב את ההודעה לשידור:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'BROADCAST'; return

    # כפתורים רגילים
    if text == '📊 הצג את כל השערים':
        msg, kb = await get_prices_text(user_id, user_name)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
    elif text == '➕ הוספת מניה':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
        count = c.fetchone()[0]; conn.close()
        limit = PREMIUM_LIMIT if user_id == ADMIN_ID else DEFAULT_LIMIT # בדיקה פשוטה למנהל
        if count >= limit:
            await update.message.reply_text(f"🚫 מגבלה של {limit} מניות.")
            return
        await update.message.reply_text("סימול המניה (למשל AAPL):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'T'
    elif text == '❌ הסרת מניה':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: await update.message.reply_text("אין מניות."); return
        kb = [[InlineKeyboardButton(f"❌ {n}", callback_data=f"del_{t}")] for n, t in rows]
        await update.message.reply_text("בחר להסרה:", reply_markup=InlineKeyboardMarkup(kb))
    
    # תהליכי קלט (States)
    elif state == 'T':
        context.user_data['temp_t'] = text.upper(); context.user_data['state'] = 'N'
        await update.message.reply_text("שם המניה (למשל אפל):")
    elif state == 'N':
        context.user_data['temp_n'] = text; context.user_data['state'] = 'P'
        await update.message.reply_text("מחיר קנייה? (או 'דלג'):", reply_markup=ReplyKeyboardMarkup([['דלג ⏩']], resize_keyboard=True))
    elif state == 'P':
        context.user_data['temp_p'] = float(text) if text != 'דלג ⏩' else 0
        context.user_data['state'] = 'Q'
        await update.message.reply_text("כמות? (או 'דלג'):")
    elif state == 'Q':
        qty = float(text) if text != 'דלג ⏩' else 0
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT INTO stocks (name, ticker, user_id, quantity, purchase_price) VALUES (?, ?, ?, ?, ?)",
                  (context.user_data['temp_n'], context.user_data['temp_t'], user_id, qty, context.user_data['temp_p']))
        conn.commit(); conn.close(); context.user_data.clear()
        await update.message.reply_text("✅ נוספה!", reply_markup=reply_markup)
    elif state == 'BROADCAST':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users"); users = c.fetchall(); conn.close()
        for u in users:
            try: await context.bot.send_message(chat_id=u[0], text=f"📢 **הודעה חשובה:**\n\n{text}", parse_mode='Markdown')
            except: pass
        await update.message.reply_text("✅ נשלח!", reply_markup=reply_markup)
        context.user_data.clear()

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user_id = update.effective_user.id
    if query.data.startswith("analyze_"):
        analysis = await get_stock_analysis(query.data.split("_")[1])
        await context.bot.send_message(chat_id=user_id, text=analysis, parse_mode='Markdown', disable_web_page_preview=True)
    elif query.data == "refresh":
        msg, kb = await get_prices_text(user_id, update.effective_user.first_name)
        try: await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
        except: pass
    elif query.data.startswith("tgp_"):
        target_id = int(query.data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("UPDATE users SET is_premium = 1 - is_premium WHERE user_id = ?", (target_id,))
        conn.commit(); conn.close()
        await query.edit_message_text("✅ סטטוס פרימיום עודכן!")
    elif query.data.startswith("del_"):
        ticker = query.data.replace("del_", "")
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("DELETE FROM stocks WHERE ticker = ? AND user_id = ?", (ticker, user_id))
        conn.commit(); conn.close()
        await query.edit_message_text(f"✅ {ticker} הוסרה.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user.id, user.first_name))
    conn.commit(); conn.close()
    kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user.id == ADMIN_ID: kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])
    await update.message.reply_text(f"{get_greeting(user.first_name)}\nברוך הבא!", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot started successfully")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
