import pandas as pd
import yfinance as yf
import requests
import time
import warnings
from datetime import datetime
import pytz
import concurrent.futures
import os
import io

warnings.filterwarnings("ignore")

# --- TELEGRAM SETUP ---
TELEGRAM_TOKEN = "8657774899:AAGKqx2_TgaoYAbUljSAXt5l9BzL_cnyCPE"
TELEGRAM_CHAT_ID = "8900320752"
TRADE_FILE = "indian_active_trades.csv"

def send_telegram_alert(message):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except: pass

def get_top_500_nse_stocks():
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        df.columns = df.columns.str.strip()
        eq_df = df[df['SERIES'] == 'EQ'].head(500) # Fetching top 500 to avoid IP Block
        eq_df['Yahoo_Ticker'] = eq_df['SYMBOL'] + ".NS"
        return eq_df[['SYMBOL', 'Yahoo_Ticker']]
    except:
        return pd.DataFrame({"SYMBOL": ["RELIANCE", "TCS", "HDFCBANK", "INFY"], "Yahoo_Ticker": ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS"]})

def calculate_rsi(data, period=14):
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# --- LIVE SCOREBOARD (TARGET & SL TRACKER) ---
def check_active_trades():
    if not os.path.exists(TRADE_FILE): return
    df = pd.read_csv(TRADE_FILE)
    active_trades = df[df['Status'] == 'Active']

    for index, row in active_trades.iterrows():
        ticker = row['Yahoo_Ticker']
        try:
            data = yf.Ticker(ticker).history(period="1d", interval="15m")
            if not data.empty:
                ltp = data['Close'].iloc[-1]
                if row['Action'] == "🟢 BUY":
                    if ltp >= row['Target']:
                        send_telegram_alert(f"🎯 TARGET HIT: {row['Stock']} \n✅ Profit Booked at ₹{ltp:,.2f} 🚀")
                        df.at[index, 'Status'] = 'Target Hit'
                    elif ltp <= row['SL']:
                        send_telegram_alert(f"🛑 STOPLOSS HIT: {row['Stock']} \n❌ Exited at ₹{ltp:,.2f} 📉")
                        df.at[index, 'Status'] = 'SL Hit'
                elif row['Action'] == "🔴 SELL":
                    if ltp <= row['Target']:
                        send_telegram_alert(f"🎯 TARGET HIT (SHORT): {row['Stock']} \n✅ Profit Booked at ₹{ltp:,.2f} 🚀")
                        df.at[index, 'Status'] = 'Target Hit'
                    elif ltp >= row['SL']:
                        send_telegram_alert(f"🛑 STOPLOSS HIT (SHORT): {row['Stock']} \n❌ Exited at ₹{ltp:,.2f} 📉")
                        df.at[index, 'Status'] = 'SL Hit'
        except: pass
    df.to_csv(TRADE_FILE, index=False)

def scan_stock(row):
    ticker = row['Yahoo_Ticker']
    symbol = row['SYMBOL']
    try:
        data = yf.Ticker(ticker).history(period="1mo", interval="15m")
        if len(data) < 30: return None

        curr = data['Close'].iloc[-1]
        curr_vol = data['Volume'].iloc[-1]
        if curr < 20 or curr_vol < 10000: return None

        sma_20 = data['Close'].rolling(window=20).mean().iloc[-1]
        std_20 = data['Close'].rolling(window=20).std().iloc[-1]
        upper_bb, lower_bb = sma_20 + (std_20 * 2), sma_20 - (std_20 * 2)

        ema_9 = data['Close'].ewm(span=9).mean().iloc[-1]
        ema_21 = data['Close'].ewm(span=21).mean().iloc[-1]
        rsi_14 = calculate_rsi(data).iloc[-1]

        avg_vol_20 = data['Volume'].rolling(window=20).mean().iloc[-1] if data['Volume'].iloc[-1] > 0 else 1
        whale_spike = curr_vol > (avg_vol_20 * 1.5)
        atr = (data['High'].iloc[-1] - data['Low'].iloc[-1]) * 1.5

        bullish = (curr > upper_bb) and (ema_9 > ema_21) and (40 < rsi_14 < 70) and whale_spike
        bearish = (curr < lower_bb) and (ema_9 < ema_21) and (30 < rsi_14 < 60) and whale_spike

        if bullish or bearish:
            action = "🟢 BUY" if bullish else "🔴 SELL"
            tgt = curr + (atr * 3) if bullish else curr - (atr * 3)
            sl = curr - (atr * 1.5) if bullish else curr + (atr * 1.5)
            return {"Stock": symbol, "Yahoo_Ticker": ticker, "Action": action, "Entry": round(curr, 2), "Target": round(tgt, 2), "SL": round(sl, 2), "Status": "Active"}
    except: return None
    return None

print("🚀 Indian Market Auto-Tracker Started...")
send_telegram_alert("🟢 System Online: Top 500 Indian Stocks Scanner & Trade Tracker Started!")

while True:
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist)
        # Market open: Mon-Fri, 9:15 AM to 3:30 PM
        is_market_open = now.weekday() < 5 and (now.hour > 9 or (now.hour == 9 and now.minute >= 15)) and (now.hour < 15 or (now.hour == 15 and now.minute <= 30))

        if is_market_open:
            # Step 1: Pehle purane trades ka result check karo (Live Scoreboard logic)
            check_active_trades()

            # Step 2: Naye stocks scan karo
            nse_stocks = get_top_500_nse_stocks()
            new_trades = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(scan_stock, row) for index, row in nse_stocks.iterrows()]
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    if res: new_trades.append(res)

            # Step 3: Agar nayi entry mili, toh CSV me save karo aur Telegram bhejo
            if new_trades:
                if os.path.exists(TRADE_FILE):
                    df = pd.read_csv(TRADE_FILE)
                    active_symbols = df[df['Status'] == 'Active']['Stock'].tolist()
                    for trade in new_trades:
                        if trade['Stock'] not in active_symbols: # Double entry se bachne ke liye
                            df = pd.concat([df, pd.DataFrame([trade])], ignore_index=True)
                            send_telegram_alert(f"🚨 NEW TRADE ALERT: {trade['Stock']}\nAction: {trade['Action']}\nEntry: ₹{trade['Entry']}\nTarget: ₹{trade['Target']}\nSL: ₹{trade['SL']}")
                    df.to_csv(TRADE_FILE, index=False)
                else:
                    df = pd.DataFrame(new_trades)
                    df.to_csv(TRADE_FILE, index=False)
                    for trade in new_trades:
                        send_telegram_alert(f"🚨 NEW TRADE ALERT: {trade['Stock']}\nAction: {trade['Action']}\nEntry: ₹{trade['Entry']}\nTarget: ₹{trade['Target']}\nSL: ₹{trade['SL']}")

            time.sleep(300) # 5 Minute wait karke wapas check karega
        else:
            time.sleep(3600) # Market band hone par server so jayega

    except Exception as e:
        print(f"Error: {e}")
        time.sleep(60)