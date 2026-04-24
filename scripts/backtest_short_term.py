#!/usr/bin/env python3
"""backtest_short_term.py — historical backtest for ShortTermSystem on XAUUSD 1h.

Pre-computes patterns + indicators once, then iterates bars efficiently.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.strategies.active.pattern_detector import PatternDetector
from trading.strategies.active.session_filter import SessionFilter


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: Literal["LONG"]
    entry_price: float
    exit_price: float
    pnl_pct: float
    pnl_abs: float
    pattern: str
    regime: str
    session: str
    atr_entry: float
    bars_held: int
    exit_reason: str


class BacktestEngine:
    def __init__(
        self,
        bb_period: int = 10,
        bb_std: float = 1.0,
        atr_period: int = 14,
        rsi_period: int = 14,
        ema_fast: int = 5,
        ema_slow: int = 20,
        initial_capital: float = 100_000.0,
        risk_pct: float = 2.0,
        sl_atr: float = 1.5,
        tp_atr: float = 2.5,
        max_bars_held: int = 8,
    ) -> None:
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.atr_period = atr_period
        self.rsi_period = rsi_period
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct
        self.sl_atr = sl_atr
        self.tp_atr = tp_atr
        self.max_bars_held = max_bars_held
        self.session_filter = SessionFilter()

        # Pre-computed indicators (set during run)
        self._bb_upper: pd.Series = None  # type: ignore[assignment]
        self._bb_middle: pd.Series = None  # type: ignore[assignment]
        self._bb_lower: pd.Series = None  # type: ignore[assignment]
        self._atr: pd.Series = None  # type: ignore[assignment]
        self._rsi: pd.Series = None  # type: ignore[assignment]
        self._ema_fast: pd.Series = None  # type: ignore[assignment]
        self._ema_slow: pd.Series = None  # type: ignore[assignment]
        self._patterns: list[dict] = []
        self._equity_curve: list[float] = []

        self.capital = initial_capital
        self.trades: list[Trade] = []
        self._position: dict = {}

    # -------------------------------------------------------------------------
    # Indicator pre-computation
    # -------------------------------------------------------------------------

    def _compute_indicators(self, df: pd.DataFrame) -> None:
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        # Bollinger Bands
        mid = close.rolling(window=self.bb_period, min_periods=self.bb_period).mean()
        std = close.rolling(window=self.bb_period, min_periods=self.bb_period).std()
        self._bb_upper = mid + std * self.bb_std
        self._bb_middle = mid
        self._bb_lower = mid - std * self.bb_std

        # ATR
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        self._atr = tr.rolling(window=self.atr_period, min_periods=self.atr_period).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=self.rsi_period, min_periods=self.rsi_period).mean()
        loss = (-delta.clip(upper=0)).rolling(window=self.rsi_period, min_periods=self.rsi_period).mean()
        rs = gain / (loss + 1e-9)
        self._rsi = 100 - 100 / (1 + rs)

        # EMA
        self._ema_fast = close.ewm(span=self.ema_fast, adjust=False).mean()
        self._ema_slow = close.ewm(span=self.ema_slow, adjust=False).mean()

        # Patterns
        detector = PatternDetector(
            atr_period=self.atr_period,
            bb_period=self.bb_period,
            bb_std=self.bb_std,
        )
        self._patterns = detector.detect(df)

        # Index patterns by timestamp for O(1) lookup
        self._pattern_index: dict[pd.Timestamp, list[dict]] = {}
        for p in self._patterns:
            ts = pd.Timestamp(p["timestamp"])
            self._pattern_index.setdefault(ts, []).append(p)

    # -------------------------------------------------------------------------
    # Bar-level signal logic
    # -------------------------------------------------------------------------

    def _signal_at_bar(
        self,
        df: pd.DataFrame,
        i: int,
        in_pos: bool,
    ) -> Literal["buy", "sell", "hold"]:
        ts = pd.Timestamp(df["timestamp"].iloc[i])
        c = float(df["close"].iloc[i])

        # Session filter
        if not self.session_filter.is_allowed(ts):
            return "hold"

        # Daily trade limit
        date_key = str(ts.date())
        daily_trades_today = sum(
            1 for t in self.trades if str(t.entry_time.date()) == date_key
        )
        if daily_trades_today >= 2:
            return "hold"

        # Daily loss limit
        today_loss = sum(
            t.pnl_pct for t in self.trades
            if str(t.exit_time.date()) == date_key and t.pnl_pct < 0
        )
        if today_loss <= -3.0:
            return "hold"

        # Pattern check
        bar_patterns = self._pattern_index.get(ts, [])

        if not in_pos:
            # Entry conditions
            bb_lo = float(self._bb_lower.iloc[i])
            rsi_val = float(self._rsi.iloc[i])
            ema_f = float(self._ema_fast.iloc[i])
            ema_s = float(self._ema_slow.iloc[i])
            atr_val = float(self._atr.iloc[i])

            # Need BB lower valid
            if pd.isna(bb_lo) or pd.isna(rsi_val) or pd.isna(ema_f) or pd.isna(ema_s):
                return "hold"

            # Entry: price near BB lower + (RSI < 35 OR EMA bullish)
            near_bb_lower = c <= bb_lo * 1.005
            rsi_oversold = rsi_val < 35
            ema_bullish = ema_f > ema_s
            atr_valid = not pd.isna(atr_val) and atr_val > 0

            if near_bb_lower and (rsi_oversold or ema_bullish) and atr_valid and bar_patterns:
                return "buy"

        else:
            # Exit conditions (always evaluate)
            return "hold"

        return "hold"

    # -------------------------------------------------------------------------
    # Main run
    # -------------------------------------------------------------------------

    def run(self, df: pd.DataFrame, symbol: str = "XAUUSD") -> list[Trade]:
        warmup = max(self.bb_period, self.atr_period, self.rsi_period, self.ema_slow, 5)
        self._compute_indicators(df)

        self.capital = self.initial_capital
        self.trades = []
        self._position = {}
        self._equity_curve = [1.0]

        for i in range(warmup, len(df)):
            ts = pd.Timestamp(df["timestamp"].iloc[i])
            h = float(df["high"].iloc[i])
            lo = float(df["low"].iloc[i])
            c = float(df["close"].iloc[i])
            sk = symbol

            in_pos = sk in self._position

            # Generate signal
            signal = self._signal_at_bar(df, i, in_pos)

            if signal == "buy" and not in_pos:
                atr_val = float(self._atr.iloc[i])
                sl_price = c - self.sl_atr * atr_val
                tp_price = c + self.tp_atr * atr_val
                risk_amt = self.capital * (self.risk_pct / 100)
                price_risk = c - sl_price
                size = risk_amt / price_risk if price_risk > 0 else 0.0
                self._position[sk] = {
                    "entry_time": ts,
                    "entry_price": c,
                    "size": size,
                    "sl": sl_price,
                    "tp": tp_price,
                    "atr_entry": atr_val,
                    "entry_idx": i,
                    "bars_held": 0,
                    "direction": "LONG",
                    "pattern": self._pattern_index.get(ts, [{}])[0].get("pattern", "ShortTerm") if self._pattern_index.get(ts) else "ShortTerm",
                }

            # Manage open position
            if sk in self._position:
                pos = self._position[sk]
                pos["bars_held"] += 1

                hit_sl = lo <= pos["sl"]
                hit_tp = h >= pos["tp"]

                if hit_sl:
                    self._close_trade(pos, pos["sl"], ts, i, "SL")
                    self._position.pop(sk, None)
                elif hit_tp:
                    self._close_trade(pos, pos["tp"], ts, i, "TP")
                    self._position.pop(sk, None)
                elif pos["bars_held"] >= self.max_bars_held:
                    self._close_trade(pos, c, ts, i, "TIME")
                    self._position.pop(sk, None)

            # Equity
            if sk in self._position:
                entry = self._position[sk]["entry_price"]
                cur_pnl = (c - entry) / entry * 100
                equity = self._equity_curve[-1] * (1 + cur_pnl / 100)
            else:
                equity = self._equity_curve[-1]
            self._equity_curve.append(equity)

        # Close open at end
        for _sk, pos in list(self._position.items()):
            c_end = float(df["close"].iloc[-1])
            self._close_trade(pos, c_end, pd.Timestamp(df["timestamp"].iloc[-1]), len(df) - 1, "END")
        self._position.clear()

        return self.trades

    def _close_trade(
        self,
        pos: dict,
        exit_price: float,
        exit_time: pd.Timestamp,
        idx: int,
        reason: str,
    ) -> None:
        entry = pos["entry_price"]
        pnl_pct = (exit_price - entry) / entry * 100
        pnl_abs = pnl_pct / 100 * self.capital
        self.capital *= 1 + pnl_pct / 100
        session = SessionFilter.session_name(exit_time)

        trade = Trade(
            entry_time=pos["entry_time"],
            exit_time=exit_time,
            direction="LONG",
            entry_price=entry,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            pnl_abs=pnl_abs,
            pattern=pos.get("pattern", "ShortTerm"),
            regime="SHORT_TERM",
            session=session,
            atr_entry=pos["atr_entry"],
            bars_held=pos["bars_held"],
            exit_reason=reason,
        )
        self.trades.append(trade)

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------

    @staticmethod
    def equity_max_dd(curve: list[float]) -> float:
        peak = 1.0
        max_dd = 0.0
        for v in curve:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd * 100

    def print_report(self, trades: list[Trade], label: str) -> None:
        if not trades:
            print("No trades.")
            return

        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct <= 0]
        wr = len(wins) / len(trades)
        avg_w = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
        avg_l = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
        total_win = sum(t.pnl_abs for t in wins)
        total_loss = abs(sum(t.pnl_abs for t in losses))
        pf = total_win / (total_loss + 1e-9)
        dd = self.equity_max_dd(self._equity_curve)
        ret = (self.capital - self.initial_capital) / self.initial_capital * 100
        expectancy = wr * avg_w + (1 - wr) * avg_l

        print("\n" + "=" * 65)
        print(f"  SHORT-TERM BACKTEST  {label}")
        print("=" * 65)
        print(f"  Capital:         ${self.capital:,.0f}  ({ret:+.2f}%)")
        print(f"  Total Trades:    {len(trades)}")
        print(f"  Win Rate:        {wr*100:.1f}%")
        print(f"  Avg Win:         +{avg_w:.3f}%")
        print(f"  Avg Loss:        {avg_l:.3f}%")
        print(f"  Profit Factor:  {pf:.2f}")
        print(f"  Max Drawdown:    {dd:.2f}%")
        print(f"  Expectancy:      {expectancy:.4f}%/trade")
        print()

        print("  By Exit Reason:")
        for reason in ["TP", "SL", "TIME", "MANUAL", "END"]:
            ts2 = [t for t in trades if t.exit_reason == reason]
            if ts2:
                avg = sum(t.pnl_pct for t in ts2) / len(ts2)
                print(f"    {reason:6s}: {len(ts2):3d} trades, avg={avg:+.3f}%")

        print()
        print("  By Session:")
        for sess in ["Asia_Late", "London", "NY"]:
            ts2 = [t for t in trades if t.session == sess]
            if ts2:
                avg = sum(t.pnl_pct for t in ts2) / len(ts2)
                wr_s = len([t for t in ts2 if t.pnl_pct > 0]) / len(ts2)
                print(f"    {sess:10s}: {len(ts2):3d} trades, WR={wr_s*100:.0f}%, avg={avg:+.3f}%")

        print()
        monthly_data: dict[str, list[Trade]] = {}
        for t in trades:
            m = t.exit_time.strftime("%Y-%m")
            monthly_data.setdefault(m, []).append(t)

        print("  Monthly:")
        for month in sorted(monthly_data):
            ts2 = monthly_data[month]
            pnl = sum(t.pnl_pct for t in ts2)
            wr_m = len([t for t in ts2 if t.pnl_pct > 0]) / len(ts2)
            style = "\033[92m" if pnl > 0 else "\033[91m"
            reset = "\033[0m"
            print(
                f"    {month}: {len(ts2)} trades, "
                f"{style}{pnl:+.2f}%{reset}, WR={wr_m*100:.0f}%"
            )

        print()
        sorted_trades = sorted(trades, key=lambda t: t.pnl_pct, reverse=True)
        print("  Top 5 Trades:")
        for t in sorted_trades[:5]:
            print(
                f"    [{t.exit_time.strftime('%Y-%m-%d')}] "
                f"{t.pnl_pct:+.3f}% {t.exit_reason} "
                f"{t.entry_price:.1f}→{t.exit_price:.1f}"
            )
        print("  Bottom 5 Trades:")
        for t in sorted_trades[-5:]:
            print(
                f"    [{t.exit_time.strftime('%Y-%m-%d')}] "
                f"{t.pnl_pct:+.3f}% {t.exit_reason} "
                f"{t.entry_price:.1f}→{t.exit_price:.1f}"
            )

        print()
        print("=" * 65)


def main() -> None:
    data_path = (
        Path(__file__).parent.parent / "backtest_data" / "candles" / "xauusd_1h.parquet"
    )
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"Loaded {len(df)} bars: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

    configs = [
        {"bb_period": 10, "bb_std": 1.0,  "ema_fast": 5,  "ema_slow": 20, "risk_pct": 2.0, "label": "BB(10,1.0) EMA(5,20)"},
        {"bb_period": 10, "bb_std": 0.5,  "ema_fast": 5,  "ema_slow": 20, "risk_pct": 2.0, "label": "BB(10,0.5) EMA(5,20)"},
        {"bb_period":  5, "bb_std": 0.5,  "ema_fast": 3,  "ema_slow": 10, "risk_pct": 2.0, "label": "BB(5,0.5)  EMA(3,10)"},
        {"bb_period": 10, "bb_std": 1.5,  "ema_fast": 5,  "ema_slow": 20, "risk_pct": 2.0, "label": "BB(10,1.5) EMA(5,20)"},
    ]

    for cfg in configs:
        engine = BacktestEngine(
            bb_period=cfg["bb_period"],
            bb_std=cfg["bb_std"],
            ema_fast=cfg["ema_fast"],
            ema_slow=cfg["ema_slow"],
            risk_pct=cfg["risk_pct"],
        )
        trades = engine.run(df)
        engine.print_report(trades, cfg["label"])
        print()


if __name__ == "__main__":
    main()
