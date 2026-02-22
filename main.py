import os
import sqlite3
import pandas as pd
from yahooquery import Ticker
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# הגדרת נתיב מסד הנתונים עבור ה-Volume ב-Railway
DB_PATH = '/app/stocks.db'

def init_db():
    # יצירת התיקייה במידה והיא לא קיימת (ליתר ביטחון)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
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
    # יצירת מקלדת כפתורים בתחתית המסך
    keyboard = [
        ['📊 הצג את כל השערים'],
        ['➕ הוספת מניה', '❓ עזרה']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    user_name = update.effective_user.first_name
    welcome_text = (
        f"שלום {user_name}! 👋\n"
        "הבוט רץ על השרת המאובטח ומוכן לפעולה.\n\n"
        "השתמש בכפתורים למטה כדי לעקוב אחרי המניות שלך."
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("מחלץ נתונים עדכניים... ⚡")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, ticker FROM stocks")
        rows = c.fetchall()
        conn.close()

        if not rows:
            await status_msg.edit_text("הרשימה שלך ריקה. השתמש בפקודה /add כדי להוסיף מניות.")
            return

        tickers_list = [row[1] for row in rows]
        ticker_names = {row[1]: row[0] for row in rows}
        
        # שליפה קבוצתית מהירה (Asynchronous)
        t = Ticker(tickers_list, asynchronous=True)
        all_data = t.price
        
        msg = "📊 **שערי מניות ושינוי יומי:**\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            if isinstance(data, str): continue # דילוג על שגיאות במניה בודדת
            
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            name = ticker_names.get(ticker)
            
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if "USDILS" in ticker else "$" if "BTC" in ticker else ""
                
                # עיצוב מיושר: שם המניה מודגש, נתונים בבלוק קוד למניעת היפוך RTL
                msg += f"🔹 **{name}**\n"
                msg += f"`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
        
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"⏰ עודכן: {pd.Timestamp.now().strftime('%H:%M:%S')}"
        
        await status_msg.edit_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await status_msg.edit_text(f"שגיאה בשליפת הנתונים: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == '📊 הצג את כל השערים':
        await all_prices(update, context)
    elif text == '❓ עזרה':
        await start(update, context)
    elif text == '➕ הוספת מניה':
        await update.message.reply_text(
            "כדי להוסיף מניה חדשה, שלח הודעה בפורמט הבא:\n"
            "`/add [סימול] [שם המניה]`\n\n"
            "לדוגמה: `/add NVDA אנבידיה`", 
            parse_mode='Markdown'
        )

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("שימוש לא תקין. דוגמה: `/add TSLA טסלה`", parse_mode='Markdown')
        return
    ticker, name = context.args[0].upper(), " ".join(context.args[1:])
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker) VALUES (?, ?)", (name, ticker))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"✅ המניה **{name}** ({ticker}) נוספה בהצלחה לרשימה.")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("נא לציין סימול להסרה. דוגמה: `/remove TSLA`", parse_mode='Markdown')
        return
    ticker = context.args[0].upper()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ?", (ticker,))
    conn.commit()
    conn.close()
    
    await update.message.reply_text(f"❌ הסימול **{ticker}** הוסר מהרשימה.")

def main():
    # אתחול בסיס הנתונים בנתיב ה-Volume
    init_db()
    
    TOKEN = "8597980945:AAEX_T-yhNkLmfoZfdEcqD6tUJdxHGBZMw0"
    app = Application.builder().token(TOKEN).build()
    
    # רישום פקודות בסיסיות
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CommandHandler("remove", remove_stock))
    
    # רישום מאזין לכפתורי המקלדת (טקסט חופשי)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🚀 הבוט רץ כעת על Railway עם אחסון קבוע...")
    app.run_polling()

if __name__ == "__main__":
    main()
