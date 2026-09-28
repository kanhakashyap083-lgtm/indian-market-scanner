import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import io
import concurrent.futures

# --- APP UI SETUP ---
st.set_page_config(page_title="Pro Market Scanner", page_icon="📈", layout="wide")
st.markdown("<h1 style='text-align: center; color: #4CAF50;'>⚡ Institutional Market Screener & Tracker</h1>", unsafe_allow_html=True)
st.markdown("<h4 style='text-align: center;'>Live 6-Layer Strategy Radar (Top 500 NSE Stocks)</h4>", unsafe_allow_html=True)
st.write("---")

# --- DATA FETCHING ---
@st.cache_data(ttl=3600)
def get_nse_stocks():
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        df.columns = df.columns.str.strip()
        eq_df = df[df['SERIES'] == 'EQ'].head(500)
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

# --- SCANNER & TRACKER LOGIC ---
def scan_stock(row):
    ticker = row['Yahoo_Ticker']
    symbol = row['SYMBOL']
    try:
        data = yf.Ticker(ticker).history(period="1mo", interval="15m")
        if len(data) < 30: return None

        curr = data['Close'].iloc[-1]
        curr_vol = data['Volume'].iloc[-1]
        high = data['High'].iloc[-1]
        low = data['Low'].iloc[-1]
        
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
            action = "🟢 STRONG BUY" if bullish else "🔴 STRONG SELL"
            tgt = curr + (atr * 3) if bullish else curr - (atr * 3)
            sl = curr - (atr * 1.5) if bullish else curr + (atr * 1.5)
            
            # --- LIVE SCOREBOARD STATUS LOGIC ---
            status = "⏳ Active (Tracking)"
            if bullish and high >= tgt:
                status = "🎯 Target Hit"
            elif bullish and low <= sl:
                status = "🛑 SL Hit"
            elif bearish and low <= tgt:
                status = "🎯 Target Hit"
            elif bearish and high >= sl:
                status = "🛑 SL Hit"

            return {
                "Stock": symbol, 
                "Signal": action, 
                "Entry Price": round(curr, 2), 
                "Live LTP": round(curr, 2),
                "Target": round(tgt, 2), 
                "Stoploss": round(sl, 2), 
                "Status": status,
                "Whale Volume": "🔥 Detected"
            }
    except: return None
    return None

# --- FRONTEND DASHBOARD ---
if st.button("🚀 FIRE SCANNER & UPDATE SCOREBOARD", use_container_width=True):
    st.info("Radar Active: Scanning 500 stocks & updating live status... Please wait 10-15 seconds.")
    nse_stocks = get_nse_stocks()
    
    if nse_stocks.empty:
        st.error("Error fetching list. Market might be offline.")
    else:
        results = []
        progress_bar = st.progress(0)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(scan_stock, row): index for index, row in nse_stocks.iterrows()}
            total = len(futures)
            completed = 0
            
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)
                completed += 1
                progress_bar.progress(completed / total)
        
        if results:
            st.success(f"✅ Scan Complete! Found {len(results)} setups with Live Status.")
            df_results = pd.DataFrame(results)
            st.dataframe(df_results, use_container_width=True)
        else:
            st.warning("⏳ No setups matched the strict 6-layer strategy right now.")
