import os
import sqlite3
import pandas as pd
import pytz
import asyncio
import logging
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# הגדרת לוגים לזיהוי תקלות
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- הגדרות מערכת ---
DB_PATH = '/database/personal_stocks.db'
ADMIN_ID = 7969303152 
DEFAULT_LIMIT = 10
PREMIUM_LIMIT = 50

def init_db():
    try:
        db_dir = os.path.dirname(DB_PATH)
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, mode=0o777, exist_ok=True)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT, user_id INTEGER)')
        c.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, first_name TEXT, is_premium INTEGER DEFAULT 0)')
        try: c.execute('ALTER TABLE stocks ADD COLUMN quantity REAL DEFAULT 0')
        except: pass
        try: c.execute('ALTER TABLE stocks ADD COLUMN purchase_price REAL DEFAULT 0')
        except: pass
        try: c.execute('ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0')
        except: pass
        conn.commit(); conn.close()
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Database Init Error: {e}")

def register_user(user_id, first_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, first_name) VALUES (?, ?)", (user_id, first_name))
        c.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (first_name, user_id))
        conn.commit(); conn.close()
    except: pass

def get_user_limit(user_id):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT is_premium FROM users WHERE user_id = ?", (user_id,))
        res = c.fetchone(); conn.close()
        return PREMIUM_LIMIT if res and res[0] == 1 else DEFAULT_LIMIT
    except: return DEFAULT_LIMIT

# --- לוגיקת נתונים משופרת ---

async def get_stock_analysis(ticker_symbol):
    try:
        t = Ticker(ticker_symbol)
        # משיכת חדשות בזהירות
        news_data = t.news(5)
        
        analysis = f"🧐 **ניתוח וחדשות עבור {ticker_symbol}:**\n\n"
        
        if not news_data or not isinstance(news_data, list):
            return analysis + "לא נמצאו חדשות עדכניות עבור מניה זו ב-Yahoo Finance."

        count = 0
        for item in news_data:
            title = item.get('title')
            link = item.get('link')
            if title and link:
                analysis += f"• [{title}]({link})\n\n"
                count += 1
            if count >= 3: break # מציג עד 3 כתבות כדי לא להעמיס

        return analysis
    except Exception as e:
        logging.error(f"Analysis Error for {ticker_symbol}: {e}")
        return f"⚠️ כרגע לא ניתן לשלוף חדשות עבור {ticker_symbol}. נסה שוב מאוחר יותר."

async def get_prices_text(user_id, user_name):
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker, quantity, purchase_price FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: return "התיק שלך ריק. לחץ על '➕ הוספת מניה'.", None
        
        tickers_list = [row[1] for row in rows]
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        prices = t.price
        
        msg = f"📊 **התיק של {user_name}:**\n━━━━━━━━━━━━━━━\n\n"
        keyboard = []
        for name, ticker, qty, buy_p in rows:
            d = prices.get(ticker, {})
            if not isinstance(d, dict): continue
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
    except Exception as e:
        logging.error(f"Price retrieval error: {e}")
        return "⚠️ שגיאה בטעינת נתונים.", None

# --- טיפול בהודעות ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    state = context.user_data.get('state')
    register_user(user_id, update.effective_user.first_name)

    admin_kb = ['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם']
    main_kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user_id == ADMIN_ID: main_kb.append(admin_kb)

    if text == '📊 הצג את כל השערים':
        msg, kb = await get_prices_text(user_id, update.effective_user.first_name)
        await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
    
    elif text == '➕ הוספת מניה':
        limit = get_user_limit(user_id)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
        if c.fetchone()[0] >= limit:
            await update.message.reply_text(f"🚫 הגעת למגבלה של {limit} מניות.")
            return
        await update.message.reply_text("סימול המניה (למשל AAPL):", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'TICKER'

    elif state == 'TICKER':
        context.user_data['temp_t'] = text.upper(); context.user_data['state'] = 'NAME'
        await update.message.reply_text("שם המניה (למשל אפל):")

    elif state == 'NAME':
        context.user_data['temp_n'] = text; context.user_data['state'] = 'PRICE'
        await update.message.reply_text("מחיר קנייה? (או 'דלג'):", reply_markup=ReplyKeyboardMarkup([['דלג ⏩']], resize_keyboard=True))

    elif state == 'PRICE':
        try:
            context.user_data['temp_p'] = float(text) if text != 'דלג ⏩' else 0
            context.user_data['state'] = 'QTY'
            await update.message.reply_text("כמות? (או 'דלג'):")
        except: await update.message.reply_text("נא להזין מספר בלבד.")

    elif state == 'QTY':
        try:
            qty = float(text) if text != 'דלג ⏩' else 0
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("INSERT INTO stocks (name, ticker, user_id, quantity, purchase_price) VALUES (?, ?, ?, ?, ?)",
                      (context.user_data['temp_n'], context.user_data['temp_t'], user_id, qty, context.user_data['temp_p']))
            conn.commit(); conn.close()
            await update.message.reply_text("✅ נשמר!", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
            context.user_data.clear()
        except: await update.message.reply_text("נא להזין מספר בלבד.")

    elif text == '❌ הסרת מניה':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: await update.message.reply_text("אין מניות."); return
        kb = [[InlineKeyboardButton(f"❌ {n}", callback_data=f"del_{t}")] for n, t in rows]
        await update.message.reply_text("בחר להסרה:", reply_markup=InlineKeyboardMarkup(kb))

    elif text == '📊 סטטיסטיקה' and user_id == ADMIN_ID:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users"); u_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1"); p_count = c.fetchone()[0]
        await update.message.reply_text(f"👥 משתמשים: {u_count}\n💎 פרימיום: {p_count}")

    elif text == '💎 ניהול פרימיום' and user_id == ADMIN_ID:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id, first_name, is_premium FROM users WHERE user_id != ?", (ADMIN_ID,))
        users = c.fetchall(); conn.close()
        if not users: await update.message.reply_text("אין משתמשים."); return
        kb = [[InlineKeyboardButton(f"{'💎' if is_p else '👤'} {name}", callback_data=f"tgp_{uid}")] for uid, name, is_p in users]
        await update.message.reply_text("שינוי סטטוס פרימיום:", reply_markup=InlineKeyboardMarkup(kb))

    elif text == '📢 הודעה לכולם' and user_id == ADMIN_ID:
        await update.message.reply_text("כתוב את ההודעה לשידור:", reply_markup=ReplyKeyboardRemove())
        context.user_data['state'] = 'BROADCAST'

    elif state == 'BROADCAST' and user_id == ADMIN_ID:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT user_id FROM users"); users = c.fetchall(); conn.close()
        for u in users:
            try:
                await context.bot.send_message(chat_id=u[0], text=f"📢 **הודעה מהנהלת הבוט:**\n\n{text}", parse_mode='Markdown')
                await asyncio.sleep(0.05)
            except: pass
        await update.message.reply_text("✅ נשלח!", reply_markup=ReplyKeyboardMarkup(main_kb, resize_keyboard=True))
        context.user_data.clear()

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); user_id = update.effective_user.id
    if query.data.startswith("analyze_"):
        ticker = query.data.split("_")[1]
        analysis = await get_stock_analysis(ticker)
        await context.bot.send_message(chat_id=user_id, text=analysis, parse_mode='Markdown', disable_web_page_preview=True)
    elif query.data == "refresh":
        msg, kb = await get_prices_text(user_id, update.effective_user.first_name)
        if kb:
            try: await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=kb, disable_web_page_preview=True)
            except: pass
    elif query.data.startswith("tgp_"):
        if user_id != ADMIN_ID: return
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
    register_user(user.id, user.first_name)
    kb = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
    if user.id == ADMIN_ID: kb.append(['📊 סטטיסטיקה', '💎 ניהול פרימיום', '📢 הודעה לכולם'])
    await update.message.reply_text(f"שלום {user.first_name}!", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__": main()
