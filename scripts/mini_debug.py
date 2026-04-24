"""Minimal debug script to trace signal flow."""
import sys

sys.path.insert(0, "/Users/zihanma/Desktop/crypto-ai-trader")

from datetime import UTC
from decimal import Decimal

import pandas as pd

from trading.backtest.store import ParquetCandleStore
from trading.strategies.active.strategy_selector import StrategySelector

store = ParquetCandleStore("/Users/zihanma/Desktop/crypto-ai-trader/backtest_data")
data = store.load(["BTCUSDT"], "1h", Decimal("10000"))

selector = StrategySelector(symbols=["BTCUSDT"])

class TrackedAdapter:
    def __init__(self, selector):
        self.selector = selector
        self._bars = None
        self._window = 120
        self._call = 0

    def generate_signals(self, symbol, df):
        self._call += 1
        print(f"  [TrackedAdapter] call={self._call} df_len={len(df)}", flush=True)

        if self._bars is None:
            self._bars = df
        else:
            self._bars = pd.concat([self._bars, df], ignore_index=True)
        if len(self._bars) > self._window:
            self._bars = self._bars.iloc[-self._window:]

        print(f"    _bars len={len(self._bars)}", flush=True)

        if len(self._bars) < 60:
            print(f"    SKIP: only {len(self._bars)} bars", flush=True)
            return []

        last_ts = self._bars["timestamp"].iloc[-1].to_pydatetime()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)

        print(f"    Calling selector... in_pos={self.selector.is_in_position(symbol)}", flush=True)
        # We need features, not raw df - use dummy for now
        cand = self.selector.select_candidate(
            symbol=symbol,
            features_15m=[],
            features_1h=[],
            features_4h=[],
            now=last_ts,
        )
        print(f"    selector returned: {cand}", flush=True)
        return []

adapter = TrackedAdapter(selector)

btc_df = data["BTCUSDT"]
print(f"\nBTCUSDT data: {len(btc_df)} rows")
print(f"First 3 timestamps: {btc_df['timestamp'].iloc[:3].tolist()}")

timeline = sorted(set(btc_df["timestamp"].tolist()))
print(f"Total timeline length: {len(timeline)}")
print(f"First 3 timeline: {timeline[:3]}")

symbols = ["BTCUSDT"]
for _i, ts in enumerate(timeline[:3]):
    for sym in symbols:
        sym_df = data[sym]
        idx_list = sym_df.index[sym_df["timestamp"] == ts].tolist()
        if not idx_list:
            print(f"  Bar ts={ts}: NO MATCH!")
            continue
        idx = idx_list[0]
        bars_up_to_t = sym_df[sym_df["timestamp"] <= ts]
        print(f"\nBar ts={ts} (idx={idx}): bars_up_to_t len={len(bars_up_to_t)}", flush=True)
        sigs = adapter.generate_signals(sym, bars_up_to_t)
