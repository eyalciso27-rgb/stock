async def all_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("מרענן נתונים... 🔄")
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
        
        t = Ticker(tickers_list, asynchronous=True, formatted=False)
        all_data = t.price
        
        msg = "📊 **שערי מניות ומדדים:**\n"
        msg += "━━━━━━━━━━━━━━━\n"
        
        for ticker in tickers_list:
            data = all_data.get(ticker, {})
            name = ticker_names.get(ticker)
            
            # בדיקה: האם קיבלנו נתונים תקינים או הודעת שגיאה (טקסט)
            if not isinstance(data, dict):
                msg += f"🔹 **{name}**\n`שגיאה: סימול לא נמצא ({ticker})`\n\n"
                continue
            
            price = data.get('regularMarketPrice')
            change_pct = data.get('regularMarketChangePercent', 0) * 100
            
            if price:
                icon = "🟢" if change_pct >= 0 else "🔴"
                trend = "+" if change_pct >= 0 else ""
                curr = "₪" if ".TA" in ticker or "USDILS" in ticker else "$"
                if "^" in ticker: curr = "" 
                
                msg += f"🔹 **{name}**\n"
                msg += f"`{curr}{price:,.2f} ({icon} {trend}{change_pct:.2f}%)`\n\n"
            else:
                msg += f"🔹 **{name}**\n`אין נתונים זמינים`\n\n"
        
        msg += "━━━━━━━━━━━━━━━\n"
        msg += f"⏰ {pd.Timestamp.now().strftime('%H:%M:%S')}"
        await status_msg.edit_text(msg, parse_mode='Markdown')
        
    except Exception as e:
        await status_msg.edit_text(f"שגיאה כללית: {e}")
