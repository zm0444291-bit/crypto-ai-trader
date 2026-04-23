"""Regression backtest — 2025 full year with StrategySelector.

Uses fully precomputed indicator arrays and O(1) CandleFeatures lookup per bar.
No per-bar EMA recalculation — all indicators precomputed once at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore
from trading.features.builder import CandleFeatures
from trading.strategies.active.strategy_selector import StrategySelector


@dataclass
class Signal:
    qty: Decimal
    side: str
    entry_atr: float | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Indicator arrays (precomputed once, reused every bar)
# ──────────────────────────────────────────────────────────────────────────────


class PrecomputedIndicators:
    """Precomputed indicator arrays for a single timeframe.

    All arrays are indexed by the bar's position in the source 15m dataframe.
    Naïve bars have None values.
    """

    def __init__(
        self,
        closes: list[Decimal],
        highs: list[Decimal] | None = None,
        lows: list[Decimal] | None = None,
        volumes: list[Decimal] | None = None,
        period_ema_fast: int = 12,
        period_ema_slow: int = 26,
        period_ema_200: int = 200,
        period_rsi: int = 14,
        period_atr: int = 14,
        period_bb: int = 20,
        bb_std: float = 2.0,
    ) -> None:
        n = len(closes)
        self.n = n
        self.closes = closes
        self.highs: list[Decimal | None] = highs if highs else [None] * n
        self.lows: list[Decimal | None] = lows if lows else [None] * n

        from trading.features.indicators import atr, ema, rsi

        self.ema_fast = ema(closes, period=period_ema_fast)
        self.ema_slow = ema(closes, period=period_ema_slow)
        self.ema_200 = ema(closes, period=period_ema_200)
        self.rsi = rsi(closes, period=period_rsi)
        self.atr = atr(highs, lows, closes, period=period_atr) if highs and lows else [None] * n

        # Trend state
        self.trend: list[str] = []
        for i in range(n):
            c, f, s = closes[i], self.ema_fast[i], self.ema_slow[i]
            if f is None or s is None:
                self.trend.append("unknown")
            elif c > s and f > s:
                self.trend.append("up")
            elif c < s and f < s:
                self.trend.append("down")
            else:
                self.trend.append("neutral")

        # Volume ratio (15m only)
        self.vol_ratio: list[Decimal | None] = [None] * n
        if volumes:
            for i in range(20, n):
                avg = sum(volumes[i - 20 : i], Decimal("0")) / Decimal("20")
                self.vol_ratio[i] = volumes[i] / avg if avg > 0 else None

        # ADX + BB bandwidth (for regime detection on 1h)
        self.adx: list[float | None] = [None] * n
        self.bb_bw: list[float | None] = [None] * n
        if highs and lows:
            self._compute_regime_arrays(highs, lows, closes, period_bb, bb_std)

    def _compute_regime_arrays(
        self,
        highs: list[Decimal],
        lows: list[Decimal],
        closes: list[Decimal],
        period_bb: int,
        bb_std: float,
    ) -> None:
        from trading.features.indicators import ema

        n = self.n
        h = [float(x) for x in highs]
        l_f = [float(x) for x in lows]
        c_f = [float(x) for x in closes]

        # True range + directional movement
        trs = [
            max(h[i] - l_f[i], abs(h[i] - c_f[i - 1]), abs(l_f[i] - c_f[i - 1]))
            for i in range(1, n)
        ]
        plus_dm = [
            max(h[i] - h[i - 1], 0) - max(l_f[i - 1] - l_f[i], 0)
            for i in range(1, n)
        ]
        minus_dm = [
            max(l_f[i - 1] - l_f[i], 0) - max(h[i] - h[i - 1], 0)
            for i in range(1, n)
        ]

        trs_d = [Decimal(str(x)) for x in trs]
        pdm_d = [Decimal(str(max(x, 0))) for x in plus_dm]
        mdm_d = [Decimal(str(max(x, 0))) for x in minus_dm]

        period = 14
        tr_s = ema(trs_d, period=period)
        pdm_s = ema(pdm_d, period=period)
        mdm_s = ema(mdm_d, period=period)

        for i in range(period, n - 1):
            tr_s_val = float(tr_s[i]) if tr_s[i] is not None else 0
            p_val = float(pdm_s[i]) if pdm_s[i] is not None else 0
            m_val = float(mdm_s[i]) if mdm_s[i] is not None else 0
            if tr_s_val > 0:
                plus_di = 100 * p_val / tr_s_val
                minus_di = 100 * m_val / tr_s_val
                dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
                self.adx[i + 1] = dx

        # Bollinger Bandwidth
        for i in range(period_bb - 1, n):
            slice_c = c_f[i - period_bb + 1 : i + 1]
            mid = sum(slice_c) / period_bb
            s_val = (sum((x - mid) ** 2 for x in slice_c) / period_bb) ** 0.5
            upper = mid + bb_std * s_val
            lower = mid - bb_std * s_val
            self.bb_bw[i] = (upper - lower) / mid if mid > 0 else 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Feature cache (O(1) per bar lookup)
# ──────────────────────────────────────────────────────────────────────────────


class FeatureCache:
    """Feature cache for the backtest — all indicators precomputed, O(1) lookup.

    For 15m: cached per bar (35,040 entries).
    For 1h/4h: cached per bar, aligned to 15m index.
    """

    def __init__(
        self, df_15m: pd.DataFrame, symbol: str = "BTCUSDT"
    ) -> None:
        self.symbol = symbol
        df = df_15m.sort_values("timestamp").reset_index(drop=True)
        self.ts_list: list[datetime] = df["timestamp"].tolist()
        n = len(df)

        closes = [Decimal(str(x)) for x in df["close"]]
        highs = [Decimal(str(x)) for x in df["high"]]
        lows = [Decimal(str(x)) for x in df["low"]]
        volumes = [Decimal(str(x)) for x in df["volume"]]

        # 15m indicators
        self.ind_15m = PrecomputedIndicators(
            closes, highs, lows, volumes
        )

        # Resample to 1h and 4h
        df_1h = self._resample(df, "1h")
        df_4h = self._resample(df, "4h")

        closes_1h = [Decimal(str(x)) for x in df_1h["close"]]
        highs_1h = [Decimal(str(x)) for x in df_1h["high"]]
        lows_1h = [Decimal(str(x)) for x in df_1h["low"]]
        self.ts_1h: list[datetime] = df_1h["timestamp"].tolist()
        self.ind_1h = PrecomputedIndicators(closes_1h, highs_1h, lows_1h)

        closes_4h = [Decimal(str(x)) for x in df_4h["close"]]
        highs_4h = [Decimal(str(x)) for x in df_4h["high"]]
        lows_4h = [Decimal(str(x)) for x in df_4h["low"]]
        self.ts_4h: list[datetime] = df_4h["timestamp"].tolist()
        self.ind_4h = PrecomputedIndicators(closes_4h, highs_4h, lows_4h)

        # Map 15m index → 1h / 4h index
        self.idx_1h = self._build_idx_map(self.ts_1h, self.ts_list)
        self.idx_4h = self._build_idx_map(self.ts_4h, self.ts_list)

        # Prebuild 1h + 4h feature lists once (small — 8761 and 2191 entries)
        print("Caching 1h/4h features...", flush=True)
        self._features_1h_all = self._make_higher_all("1h", self.ind_1h, self.ts_1h)
        self._features_4h_all = self._make_higher_all("4h", self.ind_4h, self.ts_4h)

        # Prebuild CandleFeatures for all 15m bars (O(1) per bar)
        print("Caching 15m features...", flush=True)
        self._features_15m: list[CandleFeatures] = []
        for i in range(n):
            self._features_15m.append(self._make_15m(i))

    def _resample(self, df: pd.DataFrame, freq: str) -> pd.DataFrame:
        cols = ["open", "high", "low", "close", "volume"]
        return (
            df[["timestamp"] + cols]
            .set_index("timestamp")
            .resample(freq, origin="start")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
            .dropna()
            .reset_index()
        )

    def _build_idx_map(
        self, ts_higher: list[datetime], ts_15m: list[datetime]
    ) -> list[int]:
        import bisect

        # Precompute boundaries for binary search — O(log m) per lookup
        boundaries = [ts_higher[i] for i in range(len(ts_higher))]
        idx_map: list[int] = []
        for ts in ts_15m:
            hi = bisect.bisect_right(boundaries, ts) - 1
            idx_map.append(max(0, hi))
        return idx_map

    def _make_15m(self, i: int) -> CandleFeatures:
        ind = self.ind_15m
        return CandleFeatures(
            symbol=self.symbol,
            timeframe="15m",
            candle_time=self.ts_list[i],
            close=ind.closes[i],
            high=ind.highs[i],
            low=ind.lows[i],
            ema_fast=ind.ema_fast[i],
            ema_slow=ind.ema_slow[i],
            ema_200=ind.ema_200[i],
            rsi_14=ind.rsi[i],
            atr_14=ind.atr[i],
            volume_ratio=ind.vol_ratio[i],
            trend_state=ind.trend[i],
        )

    def get(
        self, ts: datetime, n_15m: int = 60
    ) -> tuple[list[CandleFeatures], list[CandleFeatures], list[CandleFeatures]]:
        """O(1) lookup: return features for last n_15m 15m bars + all 1h/4h bars."""
        i_15m = self._find_idx(ts)
        start = max(0, i_15m - n_15m + 1)
        feats_15m = self._features_15m[start : i_15m + 1]

        i_1h = self.idx_1h[i_15m] if i_15m < len(self.idx_1h) else 0
        feats_1h = self._features_1h_all[: i_1h + 1]

        i_4h = self.idx_4h[i_15m] if i_15m < len(self.idx_4h) else 0
        feats_4h = self._features_4h_all[: i_4h + 1]

        return feats_15m, feats_1h, feats_4h

    def _make_higher_all(
        self,
        tf: str,
        ind: PrecomputedIndicators,
        ts_list: list[datetime],
    ) -> list[CandleFeatures]:
        return [
            CandleFeatures(
                symbol=self.symbol,
                timeframe=tf,
                candle_time=ts_list[i],
                close=ind.closes[i],
                high=ind.highs[i],
                low=ind.lows[i],
                ema_fast=ind.ema_fast[i],
                ema_slow=ind.ema_slow[i],
                ema_200=ind.ema_200[i],
                rsi_14=ind.rsi[i],
                atr_14=ind.atr[i],
                volume_ratio=None,
                trend_state=ind.trend[i],
            )
            for i in range(len(ts_list))
        ]

    def _make_higher(
        self,
        tf: str,
        ind: PrecomputedIndicators,
        ts_list: list[datetime],
        max_i: int,
    ) -> list[CandleFeatures]:
        feats = []
        for i in range(max_i + 1):
            feats.append(
                CandleFeatures(
                    symbol=self.symbol,
                    timeframe=tf,
                    candle_time=ts_list[i],
                    close=ind.closes[i],
                    ema_fast=ind.ema_fast[i],
                    ema_slow=ind.ema_slow[i],
                    ema_200=ind.ema_200[i],
                    rsi_14=ind.rsi[i],
                    atr_14=ind.atr[i],
                    volume_ratio=None,
                    trend_state=ind.trend[i],
                    high=ind.highs[i],
                    low=ind.lows[i],
                )
            )
        return feats

    def _find_idx(self, ts: datetime) -> int:
        n = len(self.ts_list)
        lo, hi = 0, n - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self.ts_list[mid] < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < n else n - 1


# ──────────────────────────────────────────────────────────────────────────────
# Backtest adapter
# ──────────────────────────────────────────────────────────────────────────────


class BacktestAdapter:
    def __init__(self, cache: FeatureCache, selector: StrategySelector) -> None:
        self.cache = cache
        self.selector = selector
        self._bars: pd.DataFrame | None = None
        self._window = 120  # keep last 120 bars for indicator stability

    def set_in_position(self, symbol: str, in_position: bool) -> None:
        """Called by the engine after each trade execution to sync position state."""
        self.selector.set_position_state(symbol, in_position)

    def is_in_position(self, symbol: str) -> bool:
        return self.selector.is_in_position(symbol)

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        # Accumulate historical bars — use pd.concat (fast)
        if self._bars is None:
            self._bars = df
        else:
            self._bars = pd.concat([self._bars, df], ignore_index=True)
        if len(self._bars) > self._window:
            self._bars = self._bars.iloc[-self._window :]

        if not hasattr(self, "_gen_call_count"):
            self._gen_call_count = 0
        self._gen_call_count += 1

        if len(self._bars) < 60:
            if self._gen_call_count <= 5:
                print(f"    [ADAPTER] gen_signals call={self._gen_call_count} SKIP: only {len(self._bars)} bars")
            return []

        last_ts = self._bars["timestamp"].iloc[-1].to_pydatetime()
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)

        # Every 500 calls, print a heartbeat
        if self._gen_call_count % 500 == 0:
            print(f"    [ADAPTER] gen_signals call={self._gen_call_count} last_ts={last_ts}")

        f15m, f1h, f4h = self.cache.get(last_ts, n_15m=60)
        if len(f15m) < 60:
            return []

        # Debug: print first few calls that have enough bars
        if not hasattr(self, "_debug_printed"):
            self._debug_printed = True
            print(f"    DEBUG: first call with 60+ bars: ts={last_ts} f15m={len(f15m)} f1h={len(f1h)} f4h={len(f4h)}")

        in_pos = self.selector.is_in_position(symbol)
        candidate = self.selector.select_candidate(
            symbol=symbol,
            features_15m=f15m,
            features_1h=f1h,
            features_4h=f4h,
            now=last_ts,
        )
        if candidate is None:
            if not hasattr(self, "_none_count"):
                self._none_count = 0
            self._none_count += 1
            if self._none_count <= 3:
                print(f"    [ADAPTER] bar ts={last_ts} in_pos={in_pos} → candidate=None")
            return []

        # Debug: count signal types
        if not hasattr(self, "_signal_counts"):
            self._signal_counts = {"buy": 0, "sell": 0, "none": 0}
        if candidate.side == "BUY":
            self._signal_counts["buy"] += 1
        else:
            self._signal_counts["sell"] += 1

        return [
            Signal(
                qty=Decimal("1"),
                side="buy" if candidate.side == "BUY" else "sell",
                entry_atr=(
                    float(candidate.entry_reference) if candidate.entry_reference else None
                ),
            )
        ]


# ──────────────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────────────


def run(start: datetime, end: datetime) -> dict[str, Any]:
    store = ParquetCandleStore(Path("backtest_data/candles"))
    df = store.load("BTCUSDT", "15m")
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
    print(f"Loaded {len(df)} candles", flush=True)

    cache = FeatureCache(df, symbol="BTCUSDT")
    selector = StrategySelector()
    adapter = BacktestAdapter(cache, selector)

    config = BacktestConfig(
        fee_bps=Decimal("10"),
        slippages={"default": Decimal("5")},
        initial_equity=Decimal("10_000"),
        risk_per_trade_pct=Decimal("2"),
        interval="15m",
    )

    engine = BacktestEngine(config, store)

    print("Running backtest...", flush=True)
    result = engine.run(
        strategy=adapter,
        symbols=["BTCUSDT"],
        start_time=start,
        end_time=end,
    )

    result_dict = {
        "initial_equity": result.initial_equity,
        "final_equity": result.final_equity,
        "total_return_pct": result.total_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "avg_win": result.avg_win,
        "avg_loss": result.avg_loss,
        "trades": result.trades,
        "signal_counts": getattr(adapter, "_signal_counts", None),
    }

    # Print signal counts
    if hasattr(adapter, "_signal_counts"):
        print(f"\n  [DEBUG] Adapter signals: buy={adapter._signal_counts['buy']}, sell={adapter._signal_counts['sell']}", flush=True)

    return result_dict


def main() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 12, 31, 23, 59, tzinfo=UTC)

    print("=" * 70)
    print("REGRESSION BACKTEST — BTCUSDT 15m — 2025 full year")
    print("Strategy: StrategySelector (Breakout + MeanReversion + Momentum)")
    print("=" * 70)

    result = run(start, end)

    print(f"\n  Initial Equity : ${result['initial_equity']:,.2f}")
    print(f"  Final Equity   : ${result['final_equity']:,.2f}")
    print(f"  Total Return   : {result['total_return_pct']:.2f}%")
    print(f"  Sharpe Ratio   : {result['sharpe_ratio']:.3f}")
    print(f"  Max Drawdown   : {result['max_drawdown_pct']:.2f}%")
    print(f"  Win Rate       : {result['win_rate']:.1%}")
    print(f"  Total Trades   : {result['total_trades']}")
    if result["total_trades"] > 0:
        print(f"  Avg Win        : ${result['avg_win']:,.2f}")
        print(f"  Avg Loss       : ${result['avg_loss']:,.2f}")

    print("\n  All trades:")
    for t in result["trades"]:
        pnl = t.get("pnl")
        pnl_str = f"${pnl:,.2f}" if pnl is not None else "—"
        price = t.get("entry_price") or t.get("exit_price")
        ts = str(t.get("timestamp", ""))[:19]
        side = t.get("side", "").upper()
        qty = t.get("qty", 0)
        fee = t.get("fee", 0)
        line = (
            f"    {ts}  {side:4s}  qty={float(qty):.6f}  "
            f"price=${float(price):.2f}  fee=${float(fee):.4f}  pnl={pnl_str}"
        )
        print(line)

    # Print signal counts
    adapter = None
    for _name, obj in sorted(locals().items(), key=lambda x: str(type(x[1]))):
        if hasattr(obj, "_signal_counts"):
            adapter = obj
            break
    if adapter is not None:
        print(f"\n  Adapter signals: buy={adapter._signal_counts['buy']}, sell={adapter._signal_counts['sell']}")


if __name__ == "__main__":
    main()
