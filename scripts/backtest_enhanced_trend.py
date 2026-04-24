#!/usr/bin/env python3
"""backtest_enhanced_trend.py — Focused backtest for enhanced trend parameters.

Best config from scan (2026-04-24):
  EF=12, ES=20, ADX=20, SL=2.5, TP=3.0, MB=5, RSI_conf, Vol_conf
  Score=0.832, WR=62%, PF=2.57, N=50 trades (1h XAUUSD, 18mo)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: Literal["LONG", "SHORT"]
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


@dataclass
class Position:
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    entry_time: pd.Timestamp
    sl_price: float
    tp_price: float
    atr_entry: float
    qty: float
    bars_open: int = 0
    session: str = ""


class EnhancedTrendBacktest:
    def __init__(
        self,
        ef: int = 12,
        es: int = 20,
        adx_th: float = 20.0,
        sl_atr: float = 2.5,
        tp_atr: float = 3.0,
        mb: int = 5,
        rsi_conf: bool = True,
        vol_conf: bool = True,
        initial_capital: float = 100_000.0,
        risk_pct: float = 2.0,
        max_bars_held: int = 8,
    ) -> None:
        self.ef = ef
        self.es = es
        self.adx_th = adx_th
        self.sl_atr = sl_atr
        self.tp_atr = tp_atr
        self.mb = mb
        self.rsi_conf = rsi_conf
        self.vol_conf = vol_conf
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct
        self.max_bars_held = max_bars_held

        self._bb_upper: pd.Series = None  # type: ignore[assignment]
        self._bb_middle: pd.Series = None  # type: ignore[assignment]
        self._bb_lower: pd.Series = None  # type: ignore[assignment]
        self._atr: pd.Series = None  # type: ignore[assignment]
        self._rsi: pd.Series = None  # type: ignore[assignment]
        self._ema_fast: pd.Series = None  # type: ignore[assignment]
        self._ema_slow: pd.Series = None  # type: ignore[assignment]
        self._adx: pd.Series = None  # type: ignore[assignment]
        self._ema_fast_prev: pd.Series = None  # type: ignore[assignment]
        self._ema_slow_prev: pd.Series = None  # type: ignore[assignment]
        self._vol_sma: pd.Series = None  # type: ignore[assignment]

        self.capital = initial_capital
        self.trades: list[Trade] = []
        self._position: Position | None = None
        self._equity_curve: list[float] = []

    # -------------------------------------------------------------------------
    # Session filter — active windows in UTC (exchange time)
    # -------------------------------------------------------------------------
    @staticmethod
    def _is_active_session(ts: pd.Timestamp) -> bool:
        h = ts.hour
        m = ts.minute
        total = h * 60 + m
        # Asia late: 01:00-05:00 UTC
        if 1 * 60 <= total < 5 * 60:
            return True
        # London: 08:00-12:00 UTC
        if 8 * 60 <= total < 12 * 60:
            return True
        # NY: 13:30-18:00 UTC
        if 13 * 60 + 30 <= total < 18 * 60:
            return True
        return False

    @staticmethod
    def _session_name(ts: pd.Timestamp) -> str:
        h = ts.hour
        if h < 5:
            return "Asia_Late"
        if h < 12:
            return "London"
        return "NY"

    # -------------------------------------------------------------------------
    # Indicator pre-computation
    # -------------------------------------------------------------------------
    def _compute_indicators(self, df: pd.DataFrame) -> None:
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        # Bollinger Bands
        mid = close.rolling(window=10, min_periods=10).mean()
        std = close.rolling(window=10, min_periods=10).std()
        self._bb_upper = mid + std * 2.0
        self._bb_middle = mid
        self._bb_lower = mid - std * 2.0

        # ATR
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        self._atr = tr.rolling(window=14, min_periods=14).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window=14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14, min_periods=14).mean()
        rs = gain / (loss + 1e-9)
        self._rsi = 100 - 100 / (1 + rs)

        # EMA fast and slow
        self._ema_fast = close.ewm(span=self.ef, adjust=False).mean()
        self._ema_slow = close.ewm(span=self.es, adjust=False).mean()
        # Previous bar EMA for cross detection
        self._ema_fast_prev = self._ema_fast.shift(1)
        self._ema_slow_prev = self._ema_slow.shift(1)

        # Volume SMA (20-period, scan-compatible)
        self._vol_sma = volume.rolling(window=20, min_periods=1).mean()

        # ADX
        # DX = |(+DI) - (-DI)| / (+DI + -DI) * 100
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        atr14 = self._atr
        plus_di = (plus_dm.ewm(span=14, adjust=False).mean() / atr14) * 100
        minus_di = (minus_dm.ewm(span=14, adjust=False).mean() / atr14) * 100
        dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9) * 100
        self._adx = dx.ewm(span=14, adjust=False).mean()

    # -------------------------------------------------------------------------
    # Signal generation — aligned with scan_enhanced_trend.py
    # Key differences from original:
    #   - EMA *cross* (not just alignment) for entry trigger
    #   - vol > 1.5 * vol_sma (scan-style volume confirmation)
    #   - RSI > 50 for LONG, RSI < 50 for SHORT (not rsi < 70/ > 30)
    #   - No ATR compression filter (scan doesn't use it)
    #   - Session: US 13.5-21.0 UTC OR Asia <= 3.0 (matches scan session_ok)
    # -------------------------------------------------------------------------
    def _generate_signal(self, i: int, row: pd.Series, dt: pd.Timestamp) -> Literal["LONG", "SHORT", "EXIT", "SKIP"]:
        if self._position:
            return "EXIT"

        # Session filter — MUST match scan session_ok
        h = dt.hour + dt.minute / 60.0
        if not (h <= 3.0 or (h >= 13.5 and h <= 21.0)):
            return "SKIP"

        # Current and previous bar EMA values for cross detection
        ef_cur = self._ema_fast.iloc[i]
        es_cur = self._ema_slow.iloc[i]
        ef_prv = self._ema_fast_prev.iloc[i]
        es_prv = self._ema_slow_prev.iloc[i]

        # Golden cross: fast crosses above slow
        bull_cross = ef_prv <= es_prv and ef_cur > es_cur
        # Death cross: fast crosses below slow
        bear_cross = ef_prv >= es_prv and ef_cur < es_cur

        if not bull_cross and not bear_cross:
            return "SKIP"

        # ADX confirmation
        adx_val = self._adx.iloc[i]
        if adx_val < self.adx_th:
            return "SKIP"

        # Volume confirmation: vol > 1.5 * vol_sma (scan line 184)
        if self.vol_conf:
            vol_i = float(row.get("volume", 1))
            vol_sma_i = self._vol_sma.iloc[i]
            if vol_sma_i > 0 and vol_i < 1.5 * vol_sma_i:
                return "SKIP"

        # RSI confirmation (scan lines 187-191)
        # LONG (bull_cross): RSI > 50 required
        # SHORT (bear_cross): RSI < 50 required
        rsi_val = self._rsi.iloc[i]
        if self.rsi_conf:
            if bull_cross and (pd.isna(rsi_val) or rsi_val <= 50):
                return "SKIP"
            if bear_cross and (pd.isna(rsi_val) or rsi_val >= 50):
                return "SKIP"

        # Entry
        if bull_cross:
            return "LONG"
        if bear_cross:
            return "SHORT"
        return "SKIP"

    # -------------------------------------------------------------------------
    # Backtest run
    # -------------------------------------------------------------------------
    def run(self, df: pd.DataFrame) -> None:
        self._compute_indicators(df)
        close = df["close"]
        self.capital = self.initial_capital
        self.trades = []
        self._position = None
        self._equity_curve = [self.capital]

        bars = len(df)
        for i in range(50, bars):  # WARMUP=50 matches scan
            row = df.iloc[i]
            idx = df.index[i]
            dt = pd.Timestamp(idx)

            if not self._position:
                sig = self._generate_signal(i, row, dt)
                if sig in ("LONG", "SHORT"):
                    self._open_position(sig, i, dt, row)
            else:
                self._check_exit(i, dt, row, close)

            self._equity_curve.append(self.capital)

    def _open_position(
        self,
        direction: Literal["LONG", "SHORT"],
        i: int,
        dt: pd.Timestamp,
        row: pd.Series,
    ) -> None:
        close_price = float(row["close"])
        atr = float(self._atr.iloc[i])
        sl_price = close_price - self.sl_atr * atr if direction == "LONG" else close_price + self.sl_atr * atr
        tp_price = close_price + self.tp_atr * atr if direction == "LONG" else close_price - self.tp_atr * atr

        risk_amount = self.capital * (self.risk_pct / 100)
        sl_dist = abs(close_price - sl_price)
        qty = risk_amount / sl_dist if sl_dist > 0 else 0.0

        self._position = Position(
            direction=direction,
            entry_price=close_price,
            entry_time=dt,
            sl_price=sl_price,
            tp_price=tp_price,
            atr_entry=atr,
            qty=qty,
            bars_open=0,
            session=self._session_name(dt),
        )

    def _check_exit(
        self,
        i: int,
        dt: pd.Timestamp,
        row: pd.Series,
        close: pd.Series,
    ) -> None:
        pos = self._position
        if pos is None:
            return

        cur_price = float(row["close"])
        hi_i = float(row["high"])
        lo_i = float(row["low"])
        pos.bars_open += 1

        exit_reason = ""
        exit_price = cur_price

        # SL / TP check
        if pos.direction == "LONG":
            if lo_i <= pos.sl_price:
                exit_reason = "SL"
                exit_price = pos.sl_price
            elif hi_i >= pos.tp_price:
                exit_reason = "TP"
                exit_price = pos.tp_price
        else:
            if hi_i >= pos.sl_price:
                exit_reason = "SL"
                exit_price = pos.sl_price
            elif lo_i <= pos.tp_price:
                exit_reason = "TP"
                exit_price = pos.tp_price

        # EMA cross exit — scan lines 223/245: dead_cross for LONG, gold_cross for SHORT
        if not exit_reason and i > 50:
            ef_cur = self._ema_fast.iloc[i]
            es_cur = self._ema_slow.iloc[i]
            ef_prv = self._ema_fast_prev.iloc[i]
            es_prv = self._ema_slow_prev.iloc[i]
            if pos.direction == "LONG":
                dead_cross = ef_prv >= es_prv and ef_cur < es_cur
                if dead_cross:
                    exit_reason = "CROSS"
                    exit_price = cur_price
            else:
                gold_cross = ef_prv <= es_prv and ef_cur > es_cur
                if gold_cross:
                    exit_reason = "CROSS"
                    exit_price = cur_price

        # Time exit — scan uses max_bars
        if not exit_reason and pos.bars_open >= self.max_bars_held:
            exit_reason = "TIME"

        if exit_reason:
            if pos.direction == "LONG":
                pnl_abs = (exit_price - pos.entry_price) * pos.qty
            else:
                pnl_abs = (pos.entry_price - exit_price) * pos.qty
            # pnl_pct = return on risked capital (2% of account)
            risk_amount = self.initial_capital * (self.risk_pct / 100)
            pnl_pct = pnl_abs / risk_amount * 100

            self.capital += pnl_abs
            self.trades.append(
                Trade(
                    entry_time=pos.entry_time,
                    exit_time=dt,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    pnl_pct=pnl_pct,
                    pnl_abs=pnl_abs,
                    pattern="ENHANCED_TREND",
                    regime="TREND",
                    session=pos.session,
                    atr_entry=pos.atr_entry,
                    bars_held=pos.bars_open,
                    exit_reason=exit_reason,
                )
            )
            self._position = None


# -----------------------------------------------------------------------------
def load_data() -> pd.DataFrame:
    p = Path("backtest_data/candles/xauusd_1h.parquet")
    if not p.exists():
        p = Path(__file__).parent.parent / "backtest_data/candles/xauusd_1h.parquet"
    df = pd.read_parquet(p)
    df = df.set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def print_stats(trades: list[Trade], initial: float, final: float) -> None:
    if not trades:
        print("No trades!")
        return

    risk_amount = initial * (2.0 / 100)
    wins = [t for t in trades if t.pnl_abs > 0]
    losses = [t for t in trades if t.pnl_abs <= 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    avg_win = sum(t.pnl_abs for t in wins) / len(wins) / risk_amount * 100 if wins else 0
    avg_loss = sum(t.pnl_abs for t in losses) / len(losses) / risk_amount * 100 if losses else 0
    pf = abs(sum(t.pnl_abs for t in wins) / (sum(t.pnl_abs for t in losses) + 1e-9)) if losses else float("inf")

    # Max drawdown
    equity = [initial]
    cap = initial
    for t in trades:
        cap += t.pnl_abs
        equity.append(cap)
    peak = initial
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    total_return = (final - initial) / initial * 100

    print(f"  Capital:         ${final:,.0f}  ({total_return:+.2f}%)")
    print(f"  Total Trades:    {len(trades)}")
    print(f"  Win Rate:        {wr:.1f}%")
    print(f"  Avg Win:         +{avg_win:.3f}%")
    print(f"  Avg Loss:        {avg_loss:.3f}%")
    print(f"  Profit Factor:   {pf:.2f}")
    print(f"  Max Drawdown:    {max_dd:.2f}%")
    print(f"  Expectancy:      {sum(t.pnl_pct for t in trades)/len(trades):.4f}%/trade")
    print()
    print("  By Exit Reason:")
    for reason in ["TP", "SL", "TIME"]:
        ts = [t for t in trades if t.exit_reason == reason]
        if not ts:
            continue
        avg = sum(t.pnl_pct for t in ts) / len(ts)
        print(f"    {reason:<4}: {len(ts):>3} trades, avg={avg:>+.3f}%")
    print()
    print("  By Session:")
    for session in ["Asia_Late", "London", "NY"]:
        ts = [t for t in trades if t.session == session]
        if not ts:
            continue
        wr_s = len([t for t in ts if t.pnl_abs > 0]) / len(ts) * 100
        avg_s = sum(t.pnl_pct for t in ts) / len(ts)
        print(f"    {session:<10}: {len(ts):>3} trades, WR={wr_s:.0f}%, avg={avg_s:+.3f}%")
    print()
    print(f"  Longs / Shorts: {len([t for t in trades if t.direction=='LONG'])} / {len([t for t in trades if t.direction=='SHORT'])}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced trend backtest")
    parser.add_argument("--ef", type=int, default=12)
    parser.add_argument("--es", type=int, default=20)
    parser.add_argument("--adx", type=float, default=20.0)
    parser.add_argument("--sl", type=float, default=2.5)
    parser.add_argument("--tp", type=float, default=3.0)
    parser.add_argument("--mb", type=int, default=5)
    parser.add_argument("--rsi-conf", action="store_true", default=True)
    parser.add_argument("--vol-conf", action="store_true", default=True)
    parser.add_argument("--no-rsi-conf", action="store_true")
    parser.add_argument("--no-vol-conf", action="store_true")
    args = parser.parse_args()

    rsi_conf = not args.no_rsi_conf
    vol_conf = not args.no_vol_conf

    df = load_data()
    print(f"Loaded {len(df)} bars: {df.index[0]} → {df.index[-1]}")
    print()
    print(f"Params: EF={args.ef}, ES={args.es}, ADX={args.adx}, SL={args.sl}, TP={args.tp}, MB={args.mb}, RSI_conf={rsi_conf}, Vol_conf={vol_conf}")
    print("=" * 60)

    bt = EnhancedTrendBacktest(
        ef=args.ef,
        es=args.es,
        adx_th=args.adx,
        sl_atr=args.sl,
        tp_atr=args.tp,
        mb=args.mb,
        rsi_conf=rsi_conf,
        vol_conf=vol_conf,
    )
    bt.run(df)

    print()
    print(f"  SHORT-TERM BACKTEST  EF({args.ef},{args.es})  ADX>{args.adx}  SL={args.sl} TP={args.tp}")
    print("=" * 60)
    print_stats(bt.trades, bt.initial_capital, bt.capital)

    if bt.trades:
        monthly: dict[str, list[Trade]] = {}
        for t in bt.trades:
            key = t.exit_time.strftime("%Y-%m")
            monthly.setdefault(key, []).append(t)
        print()
        print("  Monthly:")
        for month in sorted(monthly.keys()):
            ts = monthly[month]
            ret = sum(t.pnl_pct for t in ts)
            wr = len([t for t in ts if t.pnl_abs > 0]) / len(ts) * 100
            print(f"    {month}: {len(ts)} trades, {ret:+.2f}%, WR={wr:.0f}%")

        best = max(bt.trades, key=lambda t: t.pnl_pct)
        worst = min(bt.trades, key=lambda t: t.pnl_pct)
        print()
        print(f"  Best Trade:  [{best.exit_time.strftime('%Y-%m-%d')}] {best.direction} {best.pnl_pct:+.3f}% {best.exit_reason} {best.entry_price:.1f}→{best.exit_price:.1f}")
        print(f"  Worst Trade: [{worst.exit_time.strftime('%Y-%m-%d')}] {worst.direction} {worst.pnl_pct:+.3f}% {worst.exit_reason} {worst.entry_price:.1f}→{worst.exit_price:.1f}")
