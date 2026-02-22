import yfinance as yf
import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- הגדרת מסד הנתונים וברירת מחדל ---
def init_db():
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS stocks (name TEXT, ticker TEXT)''')
    
    # בדיקה אם הטבלה ריקה - אם כן, נכניס את הרשימה שביקשת
    c.execute("SELECT COUNT(*) FROM stocks")
    if c.fetchone()[0] == 0:
        default_stocks = [
            ("נאסד"ק 100", "QQQ"),
            ("S&P 500", "SPY"),
            ("מדד עולמי ACWI", "ACWI"),
            ("Bitcoin", "BTC-USD"),
            ("דולר/שקל", "USDILS=X"),
            ("מדד תא 35", "TA35.TA")
        ]
        c.executemany("INSERT INTO stocks (name, ticker) VALUES (?, ?)", default_stocks)
    
    conn.commit()
    conn.close()

# --- פונקציית שליפת נתונים ---
def get_stock_price(ticker):
    try:
        data = yf.Ticker(ticker)
        # שימוש ב-history כדי להבטיח קבלת מחיר אחרון גם למט"ח
        hist = data.history(period="1d")
        if hist.empty:
            return "אין נתונים"
        price = hist['Close'].iloc[-1]
        
        # זיהוי מטבע/סוג נכס להצגה יפה
        if "USDILS" in ticker:
            return f"₪{price:.2f}"
        if "BTC" in ticker:
            return f"${price:,.0f}"
        
        return f"{price:.2f}"
    except Exception as e:
        return "שגיאה"

# --- פקודות הבוט ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ברוך הבא לבוט המניות! 📈\n\n"
        "פקודות זמינות:\n"
        "/all - קבלת כל השערים מהרשימה\n"
        "/add [סימול] [שם] - הוספת מניה חדשה\n"
        "/remove [סימול] - הסרה מהרשימה\n"
        "/price [סימול] - בדיקת מחיר מהירה לכל מניה"
    )

async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute("SELECT name, ticker FROM stocks")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("הרשימה ריקה.")
        return

    msg = "📊 **שערי מניות ומדדים:**\n"
    msg += "--- --- --- --- --- ---\n"
    
    status_msg = await update.message.reply_text("מעדכן נתונים... 🔄")
    
    for name, ticker in rows:
        price = get_stock_price(ticker)
        msg += f"🔹 **{name}**: {price}\n"
    
    await status_msg.edit_text(msg, parse_mode='Markdown')

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("שימוש: `/add AAPL אפל`", parse_mode='Markdown')
        return
    ticker = context.args[0].upper()
    name = " ".join(context.args[1:])
    
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute("INSERT INTO stocks (name, ticker) VALUES (?, ?)", (name, ticker))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ נוסף: {name} ({ticker})")

async def remove_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    ticker = context.args[0].upper()
    conn = sqlite3.connect('stocks.db')
    c = conn.cursor()
    c.execute("DELETE FROM stocks WHERE ticker = ?", (ticker,))
    conn.commit()
    conn.close()
    await update.message.reply_text(f"❌ הוסר: {ticker}")

def main():
    init_db()
    TOKEN = "YOUR_BOT_TOKEN_HERE" # כאן שים את הטוקן מ-BotFather
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("all", all_prices))
    app.add_handler(CommandHandler("add", add_stock))
    app.add_handler(CommandHandler("remove", remove_stock))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()