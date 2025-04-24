import os
import requests
import time
import pandas as pd
import numpy as np
from datetime import datetime
import hmac
import hashlib

# === 从环境变量读取密钥（Replit Deployment Secrets）===
API_KEY = os.getenv("pionex_api_key")
SECRET_KEY = os.getenv("pionex_api_secret")
TELEGRAM_TOKEN = os.getenv("telegram_token")
TELEGRAM_CHAT_ID = "1655779827"

# === Telegram 推送 ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data)
    except Exception as e:
        print("Telegram 推送失败：", e)

# === 设置参数 ===
symbol = "SOL_USDT"
interval = "5m"
quantity_usdt = 2
position = []

# === 获取 Binance K 线 ===
def get_klines(symbol="SOLUSDT", interval="5m", limit=500):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        res = requests.get(url)
        data = res.json()
        df = pd.DataFrame(data)[[0, 2, 3, 4]]
        df.columns = ["timestamp", "high", "low", "close"]
        df[["high", "low", "close"]] = df[["high", "low", "close"]].astype(float)
        return df
    except Exception as e:
        print("获取K线数据失败：", e)
        send_telegram(f"错误：获取K线失败 - {e}")
        return None

# === 计算指标 ===
def calculate_indicators(df):
    df["EMA200"] = df["close"].ewm(span=200, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    df["TR"] = df[["high", "low", "close"]].max(axis=1) - df[["high", "low", "close"]].min(axis=1)
    df["ATR"] = df["TR"].rolling(14).mean()
    return df

# === 下单函数 ===
def place_order_pionex(side, usdt_amount):
    url = "https://api.pionex.com/api/v1/order"
    timestamp = int(time.time() * 1000)
    params = {
        "symbol": symbol,
        "side": side,
        "type": "market",
        "quoteOrderQty": usdt_amount,
        "timestamp": timestamp
    }
    query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
    signature = hmac.new(SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()
    headers = {"X-PIONEX-KEY": API_KEY}
    params["signature"] = signature
    response = requests.post(url, headers=headers, params=params)
    print(f"[{datetime.now()}] {side.upper()} 市价单：{usdt_amount} USDT，响应：", response.json())
    send_telegram(f"[{datetime.now().strftime('%m/%d %H:%M')}] 已{'买入' if side=='BUY' else '卖出'} {usdt_amount} USDT SOL")

# === 策略逻辑 ===
def run_strategy():
    global position
    df = get_klines()
    if df is None:
        return
    df = calculate_indicators(df)
    current = df.iloc[-1]
    price = current["close"]
    rsi = current["RSI"]
    ema = current["EMA200"]
    atr = current["ATR"] or 1.0
    dynamic_stop_loss = atr * 1.8

    print(f"【{datetime.now()}】价格：{price:.2f} | EMA200：{ema:.2f} | RSI：{rsi:.2f} | ATR：{atr:.2f}")

    # 进场
    if price > ema:
        if rsi <= 45 and len(position) < 1:
            position.append(price)
            place_order_pionex("BUY", quantity_usdt)
        elif rsi <= 42 and len(position) < 2:
            position.append(price)
            place_order_pionex("BUY", quantity_usdt)
        elif rsi <= 38 and len(position) < 3:
            position.append(price)
            place_order_pionex("BUY", quantity_usdt)

    # 出场逻辑
    if position:
        avg_price = np.mean(position)
        if rsi >= 70:
            place_order_pionex("SELL", quantity_usdt * len(position))
            send_telegram(f"止盈：均价 {avg_price:.2f}，现价 {price:.2f}")
            position = []
        elif price <= avg_price - dynamic_stop_loss:
            place_order_pionex("SELL", quantity_usdt * len(position))
            send_telegram(f"止损：均价 {avg_price:.2f}，现价 {price:.2f}（动态止损：{dynamic_stop_loss:.2f}）")
            position = []

# === 主循环 ===
if __name__ == "__main__":
    send_telegram("交易机器人已启动。")
    while True:
        try:
            run_strategy()
            time.sleep(300)
        except Exception as e:
            print("运行出错：", e)
            send_telegram(f"运行错误：{e}")
            time.sleep(60)
