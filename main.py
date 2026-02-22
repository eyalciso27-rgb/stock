import os
import sqlite3
import pandas as pd
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# נתיב למסד הנתונים בתוך ה-Volume ב-Railway
# אם ב-Railway הגדרת Mount Path כ- /app , הקובץ יישמר שם
DB_PATH = '/app/data/stocks.db'

def init_db():
    # וודא שהתיקייה קיימת לפני יצירת הקובץ
    dir_path = os.path.dirname(DB_PATH)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT)''')
    c.execute("SELECT COUNT(*) FROM stocks")
    if c.fetchone()[0] == 0:
        default_stocks = [
            ('נאסד"ק 100', 'QQQ'), ('S&P 500', 'SPY'),
            ('מדד עולמי ACWI', 'ACWI'), ('Bitcoin', 'BTC-USD'),
            ('דולר/שקל', 'USDILS=X'), ('מדד תא 35', 'TA35.TA')
        ]
        c.executemany("INSERT INTO stocks (name, ticker) VALUES (?, ?)", default_stocks)
    conn.commit()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['📊 הצג את כל השערים'], ['➕ הוספת מניה', '❓ עזרה']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"שלום {update.effective_user.first_name}! 🚀\nהבוט רץ מהענן ומעודכן בזמן אמת.",
        reply_markup=reply_markup
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("מרענן נתונים מהבורסה... 🔄")
    
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
        
        # יצירת אובייקט Ticker עם ביטול מטמון (Cache) כדי להבטיח נתונים טריים
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        all_data = t.price
        
        msg = "📊 **שערי מניות מעודכנים:**\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            if isinstance(data, str): continue
            
            # שליפת המחיר והשינוי
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            name = ticker_names.get(ticker)
            
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if "USDILS" in ticker else "$" if "BTC" in ticker else ""
                
                msg += f"🔹 **{name}**\n"
                msg += f"`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"⏰ זמן עדכון: {pd.Timestamp.now().strftime('%H:%M:%S')}"
        await status_msg.edit_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await status_msg.edit_text(f"שגיאה בעדכון: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 הצג את כל השערים':
        await all_prices(update, context)
    elif text == '❓ עזרה' or text == '/help':
        await start(update, context)
    elif text == '➕ הוספת מניה':
        await update.message.reply_text("הוסף בפורמט: `/add AAPL אפל`", parse_mode='Markdown')

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2: return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker) VALUES (?, ?)", (name, ticker))
    conn.commit(); conn.close()
    await update.message.reply_text(f"✅ נוסף: {name}")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    ticker = context.args[0].upper()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ?", (ticker,))
    conn.commit(); conn.close()
    await update.message.reply_text(f"❌ הוסר: {ticker}")

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CommandHandler("remove", remove_stock))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()

