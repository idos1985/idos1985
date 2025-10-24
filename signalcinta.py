import ccxt
import pandas as pd
import numpy as np
import asyncio
import telegram
from datetime import datetime, timezone

# ==================== KONFIGURASI BOT & TELEGRAM ====================
TELEGRAM_TOKEN = '8309387013:AAHHMBhUcsmBPOX2j5aEJatNmiN6VnhI2CM' # GANTI DENGAN TOKEN BOT ANDA
CHAT_ID = '7183177114' # GANTI DENGAN ID CHANNEL/GROUP ANDA

# Bursa & Timeframe
EXCHANGE_ID = 'binanceusdm' 
TIMEFRAMES = ['15m', '30m', '1h'] # Timeframe yang akan di-scan

# Konfigurasi MA (Simple Moving Average)
MA_PERIODS = [20, 50, 100]

# Jendela untuk mendeteksi Swing Highs (Trendline): 
TRENDLINE_LEFT_SPAN = 5 
TRENDLINE_RIGHT_SPAN = 5

# Filter: Skip pair jika penurunan Daily > 7%
MAX_DAILY_DROP_PERCENT = 7.0 

# --- Variabel Global untuk Pasar dan Sinyal ---
ACTIVE_SYMBOLS = []
# Menyimpan sinyal yang sudah dikirim: Key = f"{symbol}_{tf}_{timestamp_candle_tutup}_{tipe_sinyal}"
SENT_SIGNALS = {} 
# =======================================================

# Inisialisasi CCXT untuk USDⓈ-M
exchange_class = getattr(ccxt, EXCHANGE_ID)
exchange = exchange_class({
    'enableRateLimit': True,
})
# Inisialisasi Bot Telegram
bot = telegram.Bot(token=TELEGRAM_TOKEN)

# --- FUNGSI PEMBANTU INDIKATOR ---

def calculate_mas(df, ma_periods):
    """Menghitung Simple Moving Average (SMA)."""
    for period in ma_periods:
        # Menghitung MA dari harga 'close'
        df[f'MA{period}'] = df['close'].rolling(window=period, min_periods=1).mean()
    return df

def find_swing_highs(df, left_span, right_span):
    """Mendeteksi indeks Swing Highs (puncak) dari data MASA LALU."""
    highs_index = []
    # Loop hingga indeks sebelum candle terbaru (last_index - 1)
    for i in range(left_span, len(df) - right_span - 1): 
        # Cek apakah high saat ini adalah yang tertinggi dalam jendela
        is_highest = df['high'].iloc[i] == max(df['high'].iloc[i-left_span : i+right_span+1])
        if is_highest:
            highs_index.append(i)
    return highs_index

def get_trendline_value(df, last_index, left_span, right_span):
    """
    Menghitung nilai harga Trendline Resistensi (harus menurun) 
    pada indeks candle terakhir, menggunakan dua swing high MASA LALU.
    """
    
    # Mencari swing highs HANYA pada data masa lalu
    highs_index = find_swing_highs(df.iloc[:-1], left_span, right_span) 
    
    if len(highs_index) < 2:
        return None
    
    # Ambil dua swing high terakhir yang terdeteksi
    idx1, idx2 = highs_index[-2], highs_index[-1]
    high_A, high_B = df['high'].iloc[idx1], df['high'].iloc[idx2]
    
    # Wajib: Trendline harus menurun (Resistensi)
    if high_B >= high_A:
        return None 

    # Hitung persamaan garis (y = m*x + c)
    m = (high_B - high_A) / (idx2 - idx1)
    c = high_A - m * idx1
    
    # Hitung nilai trendline pada indeks candle terakhir (last_index)
    trendline_value = m * last_index + c
    return trendline_value

# --- FUNGSI DETEKSI POLA C3 (MULTI-CANDLE) ---

def check_c3_pattern(df):
    """
    Deteksi Pola C3 (3 White Soldiers) dengan kriteria MA:
    1. Ada 3 candle bullish berturut-turut (C1, C2, C3).
    2. Open C1 berada di bawah MA50 & MA100.
    3. Close C3 berada di atas MA50 & MA100.
    """
    
    # Pastikan ada cukup data (setidaknya 3 candle)
    if len(df) < 3:
        return None
    
    # Ambil 3 candle terakhir
    c3 = df.iloc[-1]   # Candle terakhir (yang baru tutup)
    c2 = df.iloc[-2]
    c1 = df.iloc[-3]
    
    # Kriteria 1: 3 candle bullish berturut-turut
    is_bullish = c3['close'] > c3['open'] and c2['close'] > c2['open'] and c1['close'] > c1['open']
    
    if not is_bullish:
        return None
        
    # Kriteria 2 & 3: Penampang (Crossing) MA50 & MA100 dari C1 ke C3
    ma50_c3 = c3['MA50']
    ma100_c3 = c3['MA100']
    
    # Cek: Open C1 di bawah MA, Close C3 di atas MA
    open_c1_below_ma = (c1['open'] < ma50_c3) and (c1['open'] < ma100_c3)
    close_c3_above_ma = (c3['close'] > ma50_c3) and (c3['close'] > ma100_c3)
    
    if open_c1_below_ma and close_c3_above_ma:
        return {
            'type': "C3 (3 SOLDIERS CROSS MA50/100)",
            'close': c3['close'],
            'MA20': c3['MA20'],
            'MA50': ma50_c3,
            'MA100': ma100_c3,
            'timestamp': c3['timestamp']
        }
        
    return None


# --- FUNGSI UTAMA DETEKSI POLA (LOGIKA DIKOMBINASIKAN) ---

def check_sakti_candle(df, tf):
    """
    Mengecek Pola CS1/CS3 (1 Candle Cross 3 MA) DAN Pola C3 (3 White Soldiers Cross 2 MA).
    """
    
    # Memastikan data cukup untuk menghitung MA, Trendline, dan pola 3WS
    if len(df) < max(MA_PERIODS) + TRENDLINE_LEFT_SPAN + TRENDLINE_RIGHT_SPAN + 3:
        return None 

    # --- 1. Cek Kriteria Breakout Trendline (WAJIB PERTAMA) ---
    last_index = len(df) - 1
    last = df.iloc[last_index] # Candle terbaru (C3 untuk pola 3WS, atau Candle tunggal untuk CS1)

    trendline_value = get_trendline_value(df, last_index, TRENDLINE_LEFT_SPAN, TRENDLINE_RIGHT_SPAN)
    
    # Jika tidak ada trendline menurun atau candle terbaru tidak breakout, KELUAR.
    if trendline_value is None or last['close'] <= trendline_value:
        return None

    # --- 2. Cek Pola CS1/CS3 (1 Candle Cross 3 MA) ---
    
    # A. Candle harus Bullish
    if last['close'] > last['open']:
        # B. Cek Kriteria 'Memotong/Menelan 3 MA' (Open < MA dan Close > MA)
        menelan_ma20 = (last['close'] > last['MA20']) and (last['open'] < last['MA20'])
        menelan_ma50 = (last['close'] > last['MA50']) and (last['open'] < last['MA50'])
        menelan_ma100 = (last['close'] > last['MA100']) and (last['open'] < last['MA100'])
        
        if menelan_ma20 and menelan_ma50 and menelan_ma100:
            return {
                'type': "CS1/CS3 (1 CANDLE POTONG 3 MA)",
                'close': last['close'],
                'MA20': last['MA20'],
                'MA50': last['MA50'],
                'MA100': last['MA100'],
                'timestamp': last['timestamp']
            }
            
    # --- 3. Cek Pola C3 (3 White Soldiers Cross MA50 & MA100) ---
    
    c3_result = check_c3_pattern(df)
    
    # Jika C3 terdeteksi (dan breakout trendline sudah terkonfirmasi di Langkah 1)
    if c3_result:
        return c3_result
        
    return None

# --- FUNGSI MANAJEMEN PASAR ---

async def load_futures_symbols():
    """Memuat semua symbol USDⓈ-M Perpetual Swaps yang aktif."""
    print("Memuat daftar semua symbol USDⓈ-M Futures (Swaps)...")
    exchange.load_markets() 
    
    global ACTIVE_SYMBOLS
    ACTIVE_SYMBOLS = [
        symbol
        for symbol, market in exchange.markets.items()
        if market['active'] and market['type'] == 'swap' and market['quote'] in ['USDT', 'USDC']
    ]
    print(f"Ditemukan {len(ACTIVE_SYMBOLS)} symbol USDⓈ-M aktif.")

async def check_daily_drop(symbol):
    """Mengecek apakah pair sudah turun lebih dari 7% dalam TF 1 hari."""
    try:
        ohlcv_daily = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=2) 
        
        if len(ohlcv_daily) < 1:
            return False 
            
        last_candle = ohlcv_daily[-1]
        open_price = last_candle[1]
        close_price = last_candle[4]
        
        price_change_percent = ((close_price - open_price) / open_price) * 100
        
        if price_change_percent < -MAX_DAILY_DROP_PERCENT:
            return True
            
    except Exception:
        return False 
        
    return False

# --- FUNGSI LOOPING ---

async def scan_symbol(symbol, tf):
    """Mengambil data dan memindai pola 'Candle Sakti' untuk satu symbol."""
    
    is_dropping = await check_daily_drop(symbol)
    if is_dropping:
        # print(f"[{datetime.now().strftime('%H:%M:%S')}] SKIP: {symbol} diabaikan (Daily Drop > {MAX_DAILY_DROP_PERCENT}%)")
        return

    try:
        # 1. Ambil data OHLCV
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=150) 
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC')

        if len(df) < max(MA_PERIODS) + 3: 
            return

        # 2. Hitung Indikator
        df = calculate_mas(df, MA_PERIODS)

        # 3. Cek Pola
        sakti_result = check_sakti_candle(df.copy(), tf)
        
        if sakti_result:
            msg_data = sakti_result
            # Kunci unik harus mencakup tipe sinyal untuk mencegah duplikat saat ada 2 tipe pola di waktu yang sama
            signal_key = f"{symbol}_{tf}_{msg_data['timestamp']}_{msg_data['type']}" 
            
            # --- Pencegahan Duplikat ---
            if signal_key in SENT_SIGNALS:
                return 
            
            SENT_SIGNALS[signal_key] = True 
            
            message = (f"🔥 **CANDLE SAKTI {msg_data['type']} TERDETEKSI!** 🔥\n"
                       f"Pasangan: `{symbol}`\n"
                       f"Timeframe: `{tf}`\n"
                       f"Harga Tutup: `${msg_data['close']:.4f}`\n"
                       f"MA20: `${msg_data['MA20']:.4f}`, MA50: `${msg_data['MA50']:.4f}`, MA100: `${msg_data['MA100']:.4f}`\n"
                       f"**Konfirmasi:** {msg_data['type']} & Breakout Trendline.\n" 
                       f"Waktu Tutup: {msg_data['timestamp'].strftime('%Y-%m-%d %H:%M UTC')}")
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sinyal Kuat: {symbol} ({tf}) - {msg_data['type']}")
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')

    except ccxt.base.errors.ExchangeError as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] CCXT Error pada {symbol} ({tf}): {e}")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error tak terduga pada {symbol} ({tf}): {e}")


async def main_loop():
    """Mengatur loop pemindaian berdasarkan Timeframe dan Symbol."""
    
    await load_futures_symbols() 
    
    while True:
        # Menghitung menit saat ini dalam UTC
        current_minute = datetime.now().astimezone(timezone.utc).minute
        tasks = []
        
        for tf in TIMEFRAMES:
            scan_interval = int(tf.replace('m', '').replace('h', '')) * (60 if 'h' in tf else 1)
            
            # Cek apakah waktu saat ini sinkron dengan interval penutupan candle
            if current_minute % scan_interval == 0:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Memulai pemindaian TF {tf} untuk {len(ACTIVE_SYMBOLS)} symbol...")
                for symbol in ACTIVE_SYMBOLS:
                    tasks.append(scan_symbol(symbol, tf))

        if tasks:
            try:
                # Menjalankan semua tugas pemindaian secara paralel.
                await asyncio.gather(*tasks)
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Pemindaian selesai.")
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Peringatan: Error saat memproses task, tetapi loop berlanjut: {e}")

        # Tunggu hingga menit berikutnya (60 detik)
        await asyncio.sleep(60)

if __name__ == '__main__':
    print("Bot Pemindai Candle Sakti USDⓈ-M Futures Dimulai...")
    try:
        # Memastikan seluruh bot berjalan secara asinkron
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\nBot dihentikan oleh pengguna.")
    except Exception as e:
        print(f"\nKesalahan fatal pada level utama: {e}")
