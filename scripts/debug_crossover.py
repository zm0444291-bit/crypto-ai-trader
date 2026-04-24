"""Debug: check EMA crossover data directly."""
import sys

sys.path.insert(0, '.')
from datetime import UTC, datetime
from pathlib import Path

from trading.backtest.store import ParquetCandleStore

store = ParquetCandleStore(Path('backtest_data/candles'))
df = store.load('BTCUSDT', '1h')

# Filter to 2025 range (naive UTC → aware)
df = df[
    (df['timestamp'] >= datetime(2025, 1, 1, tzinfo=UTC)) &
    (df['timestamp'] < datetime(2026, 1, 1, tzinfo=UTC))
].reset_index(drop=True)

print(f'2025 candles: {len(df)}')
print(f'First: {df["timestamp"].iloc[0]}')
print(f'Last:  {df["timestamp"].iloc[-1]}')

closes = df['close'].astype(float)
fast = closes.ewm(span=20, adjust=False).mean()
slow = closes.ewm(span=50, adjust=False).mean()

# Count crossovers
up_count = 0
down_count = 0
up_ts = []
down_ts = []

for i in range(1, len(fast)):
    if fast.iloc[i-1] <= slow.iloc[i-1] and fast.iloc[i] > slow.iloc[i]:
        up_count += 1
        up_ts.append(df['timestamp'].iloc[i])
    elif fast.iloc[i-1] >= slow.iloc[i-1] and fast.iloc[i] < slow.iloc[i]:
        down_count += 1
        down_ts.append(df['timestamp'].iloc[i])

print(f'\nGolden crosses (UP):  {up_count}')
print(f'Death  crosses (DOWN): {down_count}')
print(f'\nFirst 3 UP: {[str(t)[:19] for t in up_ts[:3]]}')
print(f'First 3 DOWN: {[str(t)[:19] for t in down_ts[:3]]}')

# Check if the engine actually has this data
# Engine calls generate_signals(sym, bars_up_to_t) where bars_up_to_t = df[df['timestamp'] <= ts]
# At the very first bar (2025-01-01 00:00 UTC), bars_up_to_t includes 2024-12-31 13:00:00
# That's only ~11 bars before 2025 - not enough for EMA(50)
print(f'\nAt ts={df["timestamp"].iloc[0]}, bars_up_to_t length: 1 (only itself)')
print(f'At ts={df["timestamp"].iloc[52]}, bars_up_to_t length: 53 — enough for EMA(50)')
print(f'That corresponds to: {df["timestamp"].iloc[52]}')
