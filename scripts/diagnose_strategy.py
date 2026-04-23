import sys

sys.path.insert(0, '.')
from datetime import UTC, datetime

from trading.backtest.store import ParquetCandleStore
from trading.features.indicators import ema

store = ParquetCandleStore('backtest_data/candles')
df = store.load('BTCUSDT', '1h')
df = df[(df['timestamp'] >= datetime(2025, 1, 1, tzinfo=UTC)) &
        (df['timestamp'] < datetime(2026, 1, 1, tzinfo=UTC))].copy()
df = df.reset_index(drop=True)
print(f'Loaded {len(df)} candles')

closes = df['close'].astype(float)
fast = ema(closes, 20)
slow = ema(closes, 50)

print('First few fast/slow values:')
for i in range(75, 82):
    print(f'  i={i}  close={closes.iloc[i]:.2f}  fast={fast.iloc[i]:.4f}  slow={slow.iloc[i]:.4f}')

# Find crossover points
crosses = []
for i in range(1, len(fast)):
    if fast.iloc[i-1] <= slow.iloc[i-1] and fast.iloc[i] > slow.iloc[i]:
        crosses.append((i, 'UP', df['timestamp'].iloc[i]))
    elif fast.iloc[i-1] >= slow.iloc[i-1] and fast.iloc[i] < slow.iloc[i]:
        crosses.append((i, 'DOWN', df['timestamp'].iloc[i]))

print(f'\nTotal crossover signals: {len(crosses)}')
print('First 5:', crosses[:5])
print('Last 5:', crosses[-5:])
