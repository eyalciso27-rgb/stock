import os
import sqlite3
import pandas as pd
import pytz
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# --- הגדרות מערכת ---
DB_PATH = '/database/personal_stocks.db'
ADMIN_ID = 7969303152  # ה-ID שלך כמנהל

# רשימת ברירת המחדל
DEFAULT_LIST = [
    ('נאסד"ק 100', '^NDX'), ('מדד S&P 500', 'SPY'),
    ('ביטקוין', 'BTC-USD'), ('דולר/שקל', 'USDILS=X'),
    ('מדד תא 35', 'TA35.TA')
]

# --- פונקציות בסיס נתונים ---

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    # טבלת מניות
    c.execute('CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT, user_id INTEGER)')
    # טבלת מורשים - שומרת ID ושם לניהול קל
    c.execute('CREATE TABLE IF NOT EXISTS whitelist (user_id INTEGER PRIMARY KEY, first_name TEXT)')
    # הוספת המנהל אוטומטית
    c.execute('INSERT OR IGNORE INTO whitelist (user_id, first_name) VALUES (?, ?)', (ADMIN_ID, "Manager"))
    conn.commit(); conn.close()

def is_user_allowed(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT 1 FROM whitelist WHERE user_id = ?", (user_id,))
    allowed = c.fetchone() is not None
    conn.close()
    return allowed

def ensure_default_stocks(user_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stocks WHERE user_id = ?", (user_id,))
    if c.fetchone()[0] == 0:
        for name, ticker in DEFAULT_LIST:
            c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, user_id))
        conn.commit()
    conn.close()

# --- לוגיקת תוכן ---

async def get_prices_text(user_id, user_name):
    ensure_default_stocks(user_id)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
    rows = c.fetchall(); conn.close()
    
    if not rows: return "הרשימה שלך ריקה. הוסף מניה בעזרת הכפתור למטה."
    
    tickers_list = [row[1] for row in rows]
    ticker_names = {row[1]: row[0] for row in rows}
    t = Ticker(tickers_list, asynchronous=True, formatted=False)
    all_data = t.price
    
    israel_tz = pytz.timezone('Asia/Jerusalem')
    current_time = pd.Timestamp.now(tz=israel_tz).strftime('%H:%M:%S')
    
    msg = f"📊 **השערים שלך, {user_name}:**\n━━━━━━━━━━━━━━━\n\n"
    for ticker in tickers_list:
        data = all_data.get(ticker, {})
        if not isinstance(data, dict): continue
        price = data.get('regularMarketPrice')
        change = data.get('regularMarketChangePercent', 0) * 100
        if price:
            icon = "🟢" if change >= 0 else "🔴"
            curr = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
            if "^" in ticker: curr = ""
            msg += f"🔹 **{ticker_names[ticker]}**\n`{curr}{price:,.2f} ({icon} {change:+.2f}%)`\n\n"
    
    msg += f"━━━━━━━━━━━━━━━\n⏰ עדכון: {current_time}"
    return msg

# --- פונקציות עזר ובדיקה ---

async def check_and_notify_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_allowed(user.id): return True

    # שליחת התראה למנהל אם המשתמש לא מורשה
    keyboard = [[InlineKeyboardButton("✅ אשר גישה", callback_data=f"auth_yes_{user.id}_{user.first_name}"),
                 InlineKeyboardButton("❌ דחה", callback_data=f"auth_no_{user.id}")]]
    
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 **בקשת גישה חדשה:**\nשם: {user.first_name}\nID: `{user.id}`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    
    if update.message:
        await update.message.reply_text("🚫 הגישה למערכת מוגבלת.\nבקשתך נשלחה למנהל לאישור.")
    return False

# --- פקודות וטיפול בהודעות ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_and_notify_admin(update, context):
        keyboard = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❌ הסרת מניה']]
        await update.message.reply_text(f"ברוך הבא {update.effective_user.first_name}! המערכת מוכנה.", 
                                       reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def manage_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT user_id, first_name FROM whitelist WHERE user_id != ?", (ADMIN_ID,))
    users = c.fetchall(); conn.close()

    if not users:
        await update.message.reply_text("אין משתמשים מורשים מלבדך."); return

    keyboard = [[InlineKeyboardButton(f"❌ הסר את {name} ({uid})", callback_data=f"revoke_{uid}")] for uid, name in users]
    await update.message.reply_text("בחר משתמש להסרה מהמערכת:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    # אישור משתמש חדש
    if query.data.startswith("auth_"):
        if user_id != ADMIN_ID: return
        action = "yes" if "auth_yes" in query.data else "no"
        parts = query.data.split("_")
        target_id = int(parts[2])
        target_name = parts[3] if len(parts) > 3 else "Unknown"

        if action == "yes":
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO whitelist (user_id, first_name) VALUES (?, ?)", (target_id, target_name))
            conn.commit(); conn.close()
            await query.edit_message_text(f"✅ אושר: {target_name} ({target_id})")
            try: await context.bot.send_message(chat_id=target_id, text="🎊 הגישה שלך אושרה! שלח /start.")
            except: pass
        else:
            await query.edit_message_text(f"❌ המשתמש נדחה.")

    # הסרת משתמש קיים
    elif query.data.startswith("revoke_"):
        if user_id != ADMIN_ID: return
        target_id = int(query.data.split("_")[1])
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("DELETE FROM whitelist WHERE user_id = ?", (target_id,))
        conn.commit(); conn.close()
        await query.edit_message_text(f"🚫 הגישה ל-{target_id} הוסרה.")
        try: await context.bot.send_message(chat_id=target_id, text="🚫 גישתך למערכת הופסקה.")
        except: pass

    # רענון והסרת מניה
    elif is_user_allowed(user_id):
        if query.data == "refresh":
            new_text = await get_prices_text(user_id, update.effective_user.first_name)
            try: await query.edit_message_text(new_text, parse_mode='Markdown', 
                                               reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענון", callback_data="refresh")]]))
            except: pass
        elif query.data.startswith("del_"):
            ticker = query.data.replace("del_", "")
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("DELETE FROM stocks WHERE ticker = ? AND user_id = ?", (ticker, user_id))
            conn.commit(); conn.close()
            await query.edit_message_text(f"✅ המניה {ticker} הוסרה.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_and_notify_admin(update, context): return
    text = update.message.text
    user_id = update.effective_user.id

    if text == '📊 הצג את כל השערים':
        msg = await get_prices_text(user_id, update.effective_user.first_name)
        await update.message.reply_text(msg, parse_mode='Markdown', 
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 רענון", callback_data="refresh")]]))
    elif text == '❌ הסרת מניה':
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks WHERE user_id = ?", (user_id,))
        rows = c.fetchall(); conn.close()
        if not rows: await update.message.reply_text("הרשימה ריקה."); return
        keyboard = [[InlineKeyboardButton(f"❌ {n}", callback_data=f"del_{t}")] for n, t in rows]
        await update.message.reply_text("בחר להסרה:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif text == '➕ הוספת מניה':
        await update.message.reply_text("להוספה: `/add [סימול] [שם]`", parse_mode='Markdown')

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_and_notify_admin(update, context): return
    if len(context.args) < 2: return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker, user_id) VALUES (?, ?, ?)", (name, ticker, update.effective_user.id))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ המניה **{name}** נוספה.")

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CommandHandler("manage", manage_users))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__": main()
