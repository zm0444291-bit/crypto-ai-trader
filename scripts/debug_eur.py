import sys, pandas as pd
from datetime import datetime, timezone
sys.path.insert(0, '.')
from scripts.scan_daily_strategies import RSI_14_30_70, load_ohlc

df = load_ohlc('eurusd', '1d')
print('EURUSD 1d:', len(df), 'rows, close:', df['close'].min(), '~', df['close'].max())
df23 = df[(df.timestamp >= datetime(2023,1,1,tzinfo=timezone.utc)) &
           (df.timestamp <= datetime(2023,12,31,tzinfo=timezone.utc))].copy()
for c in ['open','high','low','close','volume']:
    df23[c] = df23[c].astype(float)

sigs = RSI_14_30_70(df23)
print('EURUSD 2023 signals:', len(sigs))
for s in sigs[:10]:
    print(' ', s)

equity = 10000.0
pos = None; entry = 0.0
for side, price, idx in sigs:
    if side == 'buy':
        if pos == 'short':
            equity *= (1 + (entry - price)/entry)
        entry = price; pos = 'long'
    elif side == 'sell':
        if pos == 'long':
            equity *= (1 + (price - entry)/entry)
        entry = price; pos = 'short'
print('EURUSD 2023 equity:', round(equity,4), 'ret:', round((equity-10000)/10000*100,4), '%')
