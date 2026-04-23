import sys

sys.path.insert(0, '.')
from datetime import datetime

from trading.backtest.store import ParquetCandleStore

store = ParquetCandleStore('backtest_data/candles')
df = store.load('BTCUSDT', '1h')
print('dtypes:', df.dtypes.to_dict())
print('first ts:', df['timestamp'].iloc[0])
print('last ts:', df['timestamp'].iloc[-1])
print('tz:', df['timestamp'].iloc[0].tzinfo)
# Check filtered
ts = df['timestamp']
mask = (ts >= datetime(2025, 1, 1)) & (ts < datetime(2026, 1, 1))
print('filtered rows:', mask.sum())
print('first 3 filtered:', ts[mask].head(3).tolist())
print('last 3 filtered:', ts[mask].tail(3).tolist())
