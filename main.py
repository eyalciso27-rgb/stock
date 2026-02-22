import os
import sqlite3
import pandas as pd
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# פתרון לבעיית הנתיב בעברית ואימות SSL במחשב האישי
os.environ['CURL_CA_BUNDLE'] = ''

def init_db():
    conn = sqlite3.connect('stocks.db')
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
    # הגדרת הכפתורים - וודא שאתה שולח /start עם סלאש רגיל
    keyboard = [
        ['📊 הצג את כל השערים'],
        ['➕ הוספת מניה', '❓ עזרה']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        f"שלום {update.effective_user.first_name}! 👋\nהתפריט מופיע כעת למטה.",
        reply_markup=reply_markup
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("מחלץ נתונים... ⚡")
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute("SELECT name, ticker FROM stocks")
    rows = c.fetchall()
    conn.close()

    tickers_list = [row[1] for row in rows]
    ticker_names = {row[1]: row[0] for row in rows}
    
    try:
        t = Ticker(tickers_list, verify=False, asynchronous=True)
        all_data = t.price
        
        # עיצוב חדש כדי למנוע בלגן בעין
        msg = "📊 **שערי מניות:**\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            name = ticker_names.get(ticker)
            
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if "USDILS" in ticker else "$" if "BTC" in ticker else ""
                
                # שם המניה בשורה אחת, הנתונים בשורה נפרדת בתוך בלוק קוד
                msg += f"🔹 {name}\n"
                msg += f"`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"⏰ {pd.Timestamp.now().strftime('%H:%M:%S')}"
        await status_msg.edit_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await status_msg.edit_text(f"שגיאה: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 הצג את כל השערים':
        await all_prices(update, context)
    elif text == '❓ עזרה':
        await start(update, context)
    elif text == '➕ הוספת מניה':
        await update.message.reply_text("הקלד: `/add [סימול] [שם]`", parse_mode='Markdown')

def main():
    init_db()
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("all", all_prices))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 הבוט רץ! שלח /start (עם סלאש רגיל) בטלגרם.")
    app.run_polling()

if __name__ == "__main__":
    main()
