import os
import requests
import time
import numpy as np
from telegram import Bot
from datetime import datetime

# === CONFIGURATION ===
BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID = os.environ['CHAT_ID']

PRICE_CHANGE_THRESHOLD = 4  # % movement trigger
RSI_THRESHOLD = 65
MAX_PRICE = 1.5
UPDATE_INTERVAL = 5  # seconds
COOLDOWN_SECONDS = 600  # 10-minute cooldown

bot = Bot(token=BOT_TOKEN)
last_alert_time = {}  # Track last alert time per symbol

# === Fetch tradable symbols from MEXC USDT-M futures ===
def get_mexc_usdt_futures_symbols():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    response = requests.get(url)
    symbols = []
    if response.status_code == 200:
        data = response.json().get("data", [])
        for item in data:
            if item["quoteCoin"] == "USDT" and int(item["maxLeverage"]) >= 50:
                symbols.append(item["symbol"].replace("_", "").upper())
    return symbols

VALID_SYMBOLS = get_mexc_usdt_futures_symbols()

# === RSI Calculation ===
def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = np.diff(prices)
    ups = deltas[deltas > 0].sum() / period
    downs = -deltas[deltas < 0].sum() / period
    rs = ups / downs if downs != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# === Alert Sender ===
def send_alert(symbol, price, change, interval):
    now = datetime.utcnow()

    # Check cooldown
    if symbol in last_alert_time:
        elapsed = (now - last_alert_time[symbol]).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            return

    message = (
        f"🚨 {symbol} moved {change:.2f}% in last {interval} min\n"
        f"Price: ${price:.4f}"
    )
    bot.send_message(chat_id=CHAT_ID, text=message)
    last_alert_time[symbol] = now

# === Price Checker ===
def fetch_price_changes():
    url = "https://api.mexc.com/api/v3/ticker/price"
    response = requests.get(url)
    if response.status_code != 200:
        print("❌ Failed to fetch price data.")
        return

    data = response.json()
    prices_now = {
        coin['symbol']: float(coin['price']) 
        for coin in data if coin['symbol'].endswith("USDT")
    }

    for symbol, current_price in prices_now.items():
        if symbol not in VALID_SYMBOLS or current_price > MAX_PRICE:
            continue

        # Get 5-min candles
        kline_url = f"https://api.mexc.com/api/v3/klines?symbol={symbol}&interval=5m&limit=100"
        kline_response = requests.get(kline_url)
        if kline_response.status_code != 200:
            continue

        candles = kline_response.json()
        closes = [float(c[4]) for c in candles]

        if len(closes) < 15:
            continue

        rsi = calculate_rsi(closes[-15:])
        if rsi is None or rsi < RSI_THRESHOLD:
            continue

        price_5m_ago = closes[-2]
        price_15m_ago = closes[-4]

        change_5m = ((current_price - price_5m_ago) / price_5m_ago) * 100
        change_15m = ((current_price - price_15m_ago) / price_15m_ago) * 100

        if abs(change_5m) >= PRICE_CHANGE_THRESHOLD:
            send_alert(symbol, current_price, change_5m, 5)
        elif abs(change_15m) >= PRICE_CHANGE_THRESHOLD:
            send_alert(symbol, current_price, change_15m, 15)

# === Main Loop ===
print("🤖 Bot is running. Waiting for triggers...")

while True:
    try:
        fetch_price_changes()
        time.sleep(UPDATE_INTERVAL)
    except Exception as e:
        print(f"⚠️ Error: {e}")
        time.sleep(UPDATE_INTERVAL)
