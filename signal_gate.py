import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime, timezone, timedelta
import logging
from collections import defaultdict
import requests

# Konfigurasi
TIMEFRAMES = ['1m', '5m', '1h']
EMA_SHORT = 50
EMA_LONG = 200
TAKE_PROFIT_PERCENT = 2.0
STOP_LOSS_PERCENT = 1.0

# Discord Config
DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/xxxxxx'

# Setup Exchange - Gate.io
exchange = ccxt.gate({
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot'
    }
})

# Zona waktu WIB
WIB = timezone(timedelta(hours=7))

# Sistem Anti-Duplikat
signal_history = defaultdict(dict)

def send_discord_message(content):
    try:
        payload = {
            "content": content,
            "username": "EMA Signal Bot (Gate.io)"
        }
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Discord send error: {str(e)}")

def get_all_spot_pairs():
    try:
        markets = exchange.load_markets()
        usdt_pairs = []
        
        for symbol, market in markets.items():
            if (market['spot'] and 
                market['active'] and 
                market['quote'] == 'USDT'):
                
                # Cek volume dengan fallback ke baseVolume jika quoteVolume tidak ada
                volume = float(market.get('quoteVolume', market.get('baseVolume', 0)))
                usdt_pairs.append((symbol, volume))
        
        # Urutkan berdasarkan volume (descending)
        usdt_pairs.sort(key=lambda x: x[1], reverse=True)
        return [pair[0] for pair in usdt_pairs[:50]]  # Ambil 50 teratas
        
    except Exception as e:
        logging.error(f"Error loading markets: {str(e)}")
        return [
            'ADA/USDT', 'TRX/USDT', 'NEAR/USDT', 'SHIB/USDT',
            'PEPE/USDT', 'BTC/USDT', 'ETH/USDT', 'ETC/USDT'
        ]  # Fallback ke pair default jika error

PAIRS = get_all_spot_pairs()

def calculate_emas(closes):
    df = pd.DataFrame({'close': closes})
    return (
        df['close'].ewm(span=EMA_SHORT, adjust=False).mean().iloc[-1],
        df['close'].ewm(span=EMA_LONG, adjust=False).mean().iloc[-1]
    )

def generate_signal_message(pair, tf, data):
    arrow = "🟢" if data['signal'] == 'BUY' else "🔴"
    return (
        f"{arrow} **{pair} {tf} Signal**\n"
        f"```\n"
        f"Type:       {data['signal']}\n"
        f"Price:      {data['price']:.6f}\n"
        f"EMA{EMA_SHORT}:     {data['ema50']:.6f}\n"
        f"EMA{EMA_LONG}:    {data['ema200']:.6f}\n"
        f"Take Profit: {data['take_profit']:.6f}\n"
        f"Stop Loss:   {data['stop_loss']:.6f}\n"
        f"```\n"
        f"Time: {data['time'].strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
        f"Exchange: Gate.io"
    )

def monitor():
    while True:
        try:
            for pair in PAIRS:
                for tf in TIMEFRAMES:
                    try:
                        # Fetch data dengan error handling
                        data = None
                        for _ in range(3):  # 3x retry
                            try:
                                data = exchange.fetch_ohlcv(pair, tf, limit=EMA_LONG+10)
                                break
                            except Exception as e:
                                logging.warning(f"Retry fetching {pair} {tf}: {str(e)}")
                                time.sleep(5)
                        
                        if not data or len(data) < EMA_LONG:
                            continue
                            
                        closes = np.array([x[4] for x in data])
                        current_price = closes[-1]
                        ema50, ema200 = calculate_emas(closes)
                        
                        current_signal = 'BUY' if ema50 > ema200 else 'SELL'
                        signal_key = f"{pair}|{tf}"
                        
                        if (signal_key not in signal_history or 
                            signal_history[signal_key]['signal'] != current_signal):
                            
                            # Hitung TP/SL
                            if current_signal == 'BUY':
                                tp = current_price * (1 + TAKE_PROFIT_PERCENT/100)
                                sl = current_price * (1 - STOP_LOSS_PERCENT/100)
                            else:
                                tp = current_price * (1 - TAKE_PROFIT_PERCENT/100)
                                sl = current_price * (1 + STOP_LOSS_PERCENT/100)
                            
                            signal_data = {
                                'signal': current_signal,
                                'price': current_price,
                                'ema50': ema50,
                                'ema200': ema200,
                                'take_profit': tp,
                                'stop_loss': sl,
                                'time': datetime.now(WIB)
                            }
                            
                            signal_history[signal_key] = signal_data
                            message = generate_signal_message(pair, tf, signal_data)
                            send_discord_message(message)
                            time.sleep(1)  # Jeda antar pesan
                            
                    except Exception as e:
                        logging.error(f"Error processing {pair} {tf}: {str(e)}")
                        time.sleep(10)
            
            time.sleep(60)  # Interval scanning
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"Monitor error: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('gateio_signals.log'),
            logging.StreamHandler()
        ]
    )
    
    logging.info("Starting Gate.io EMA Signal Bot")
    monitor()
