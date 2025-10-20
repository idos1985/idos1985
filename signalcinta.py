import ccxt 
import pandas as pd
import asyncio
import aiohttp
from datetime import datetime, timezone

# === ISI MANUAL ===
TELEGRAM_TOKEN = "8309387013:AAHHMBhUcsmBPOX2j5aEJatNmiN6VnhI2CM" 
CHAT_ID = "7183177114" 

# === KONFIGURASI SCAN TIMEFRAME ===
TIMEFRAMES = {
    "15m": 15 * 60,   # scan tiap 15 menit
    "30m": 31 * 60,   # scan tiap 31 menit
    "1h": 61 * 60,    # scan tiap 61 menit
    "2h": 121 * 60    # scan tiap 121 menit
}

exchange = ccxt.binance({
    'options': {'defaultType': 'future'}  # Binance Futures (USDT-M)
})

sent_signals = set()  # Menyimpan sinyal yang sudah dikirim

# === FUNGSI KIRIM PESAN TELEGRAM ===
async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    async with aiohttp.ClientSession() as session:
        await session.post(url, data=payload)

# === CEK SINYAL CANDLE MENELAN MA20, MA50, MA100 ===
def check_signal(df):
    last = df.iloc[-1]
    open_p, close_p = last['open'], last['close']
    ma20 = df['close'].rolling(window=20).mean().iloc[-1]
    ma50 = df['close'].rolling(window=50).mean().iloc[-1]
    ma100 = df['close'].rolling(window=100).mean().iloc[-1]
    waktu_close = last['time'].strftime('%Y-%m-%d %H:%M UTC')

    # Pastikan semua MA sudah terbentuk
    if pd.isna(ma20) or pd.isna(ma50) or pd.isna(ma100):
        return None, None

    # === BULLISH ===
    # Candle hijau menelan MA20, MA50, MA100 (open di bawah MA20, close di atas MA100)
    if close_p > open_p and open_p < ma20 < ma50 < ma100 < close_p:
        msg = (
            f"🟢 [BULLISH - Candle Menelan MA20, MA50, MA100]\n"
            f"Pair: {df.iloc[-1]['symbol']}\n"
            f"Timeframe: {df.iloc[-1]['tf']}\n"
            f"Close: {waktu_close}\n"
            f"Price: {close_p:.6f}\n"
            f"MA20: {ma20:.6f}\n"
            f"MA50: {ma50:.6f}\n"
            f"MA100: {ma100:.6f}\n"
            f"Kriteria: open < MA20 < MA50 < MA100 < close ✅"
        )
        return msg, "BULLISH"

    # === BEARISH ===
    # Candle merah menelan MA20, MA50, MA100 (open di atas MA20, close di bawah MA100)
    if close_p < open_p and close_p < ma100 < ma50 < ma20 < open_p:
        msg = (
            f"🔴 [BEARISH - Candle Menelan MA20, MA50, MA100]\n"
            f"Pair: {df.iloc[-1]['symbol']}\n"
            f"Timeframe: {df.iloc[-1]['tf']}\n"
            f"Close: {waktu_close}\n"
            f"Price: {close_p:.6f}\n"
            f"MA20: {ma20:.6f}\n"
            f"MA50: {ma50:.6f}\n"
            f"MA100: {ma100:.6f}\n"
            f"Kriteria: close < MA100 < MA50 < MA20 < open ✅"
        )
        return msg, "BEARISH"

    return None, None

# === MENGAMBIL DATA DAN DETEKSI SINYAL ===
def get_ma_signals(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=150)
        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
        df['time'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df['symbol'] = symbol
        df['tf'] = timeframe

        msg, signal_type = check_signal(df)
        if not msg:
            return None

        # buat ID unik untuk mencegah duplikat
        signal_id = f"{symbol}-{timeframe}-{df.iloc[-1]['time']}-{signal_type}"
        if signal_id in sent_signals:
            return None  # skip duplikat
        sent_signals.add(signal_id)

        return msg

    except Exception as e:
        print(f"Error {symbol} {timeframe}: {e}")
        return None

# === SCAN SEMUA PAIR USDT FUTURES ===
async def scan_all_pairs():
    markets = exchange.load_markets()
    symbols = [s for s in markets if s.endswith('/USDT')]
    print(f"Memindai {len(symbols)} pair di Binance Futures (USDT-M)...\n")

    while True:
        for tf, delay in TIMEFRAMES.items():
            print(f"[SCAN] Timeframe: {tf} - {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
            for symbol in symbols:
                signal = get_ma_signals(symbol, tf)
                if signal:
                    print(signal)
                    await send_telegram_message(signal)

            print(f"Selesai scan TF {tf}, tunggu {delay//60} menit...\n")
            await asyncio.sleep(delay)

# === PROGRAM UTAMA ===
async def main():
    print("🚀 Bot berjalan... Deteksi 1 Candle yang menelan MA20, MA50, dan MA100 (termasuk TF 15m)\n")
    await scan_all_pairs()

if __name__ == "__main__":
    asyncio.run(main())
