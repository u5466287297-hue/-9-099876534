from flask import Flask, render_template, jsonify, request
import yfinance as yf
import pandas as pd
import datetime
import threading
from collections import defaultdict, deque

app = Flask(__name__)

# ===================== Индикатори =====================
def compute_indicators(data):
    data["EMA5"] = data["Close"].ewm(span=5, adjust=False).mean()
    data["EMA20"] = data["Close"].ewm(span=20, adjust=False).mean()

    delta = data["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    data["RSI"] = 100 - (100 / (1 + rs))

    ema12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema26 = data["Close"].ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()

    high_low = data["High"] - data["Low"]
    high_close = (data["High"] - data["Close"].shift()).abs()
    low_close = (data["Low"] - data["Close"].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    tr = ranges.max(axis=1)
    data["ATR"] = tr.rolling(14).mean()
    return data


# ===================== Настройки =====================
ASSETS = {
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "AUD/USD": "AUDUSD=X"
}

current_asset = "EUR/USD"
last_signal = {a: None for a in ASSETS}
signal_history = {a: deque(maxlen=20) for a in ASSETS}

pending_signal = None
pending_asset = None
pending_timer = None
pending_expire_time = None


# ===================== Сигнали =====================
def get_signal(symbol):
    data = yf.download(symbol, interval="1m", period="1d")
    if len(data) < 30:
        return None, data

    data = compute_indicators(data)

    ema5 = data["EMA5"].iloc[-1]
    ema20 = data["EMA20"].iloc[-1]
    rsi = data["RSI"].iloc[-1]
    macd = data["MACD"].iloc[-1]
    signal_line = data["MACD_Signal"].iloc[-1]
    atr = data["ATR"].iloc[-1]

    signal = None
    if ema5 > ema20 and rsi > 50 and macd > signal_line and atr > 0:
        signal = "BUY"
    elif ema5 < ema20 and rsi < 50 and macd < signal_line and atr > 0:
        signal = "SELL"
    return signal, data


def trigger_signal_execution(asset, signal):
    global last_signal, signal_history, pending_signal, pending_timer, pending_expire_time, pending_asset
    last_signal[asset] = signal
    signal_history[asset].appendleft(f"{datetime.datetime.now().strftime('%H:%M:%S')} - EXECUTED {signal}")
    pending_signal = None
    pending_asset = None
    pending_timer = None
    pending_expire_time = None


# ===================== API =====================
@app.route("/api/signal")
def api_signal():
    global current_asset, pending_signal, pending_asset, pending_timer, pending_expire_time
    asset = request.args.get("asset", current_asset)
    current_asset = asset

    signal, data = get_signal(ASSETS[asset])

    if signal and signal != last_signal[asset] and not pending_signal:
        pending_signal = signal
        pending_asset = asset
        signal_history[asset].appendleft(f"{datetime.datetime.now().strftime('%H:%M:%S')} - UPCOMING {signal} (20s)")
        pending_expire_time = datetime.datetime.now() + datetime.timedelta(seconds=20)
        pending_timer = threading.Timer(20, trigger_signal_execution, args=[asset, signal])
        pending_timer.start()

    countdown = None
    if pending_expire_time and pending_asset == asset:
        countdown = max(0, int((pending_expire_time - datetime.datetime.now()).total_seconds()))

    return jsonify({
        "asset": asset,
        "assets": list(ASSETS.keys()),
        "signal": pending_signal if (pending_signal and pending_asset == asset) else (last_signal[asset] if last_signal[asset] else "NONE"),
        "history": list(signal_history[asset]),
        "all_signals": {a: list(h) for a, h in signal_history.items()},
        "countdown": countdown,
        "chart": {
            "labels": [str(i) for i in data.index[-50:]],
            "close": list(data["Close"].iloc[-50:]),
            "ema5": list(data["EMA5"].iloc[-50:]),
            "ema20": list(data["EMA20"].iloc[-50:]),
            "rsi": list(data["RSI"].iloc[-50:]),
            "macd": list(data["MACD"].iloc[-50:]),
            "macd_signal": list(data["MACD_Signal"].iloc[-50:]),
            "atr": list(data["ATR"].iloc[-50:])
        }
    })


@app.route("/")
def dashboard():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
