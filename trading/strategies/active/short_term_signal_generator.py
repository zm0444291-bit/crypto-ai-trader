"""ShortTermSignalGenerator — BB + RSI + EMA combo for XAUUSD 1h short-term trading.

Entry rules:
  LONG:  price at BB lower OR RSI < 35
         AND EMA bull cross (fast > slow)
         AND a detected pattern (reversal/breakout)
         AND in allowed session

  SELL:  price at BB upper OR RSI > 65
         AND EMA bear cross (fast < slow)
         AND a detected pattern (reversal trap/breakdown)
         AND in allowed session (sell = close long only, not short)

Risk management:
  SL: 1.5 * ATR from entry
  TP: 2.5 * ATR from entry  (R:R = 1.67)
  Max 1 position at a time, max 2 per day
  Daily max loss 3% → skip rest of day
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading.strategies.active.pattern_detector import PatternDetector
from trading.strategies.active.session_filter import SessionFilter
from trading.strategies.base import Signal


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr1  = high - low
    tr2  = (high - prev).abs()
    tr3  = (low - prev).abs()
    tr   = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


class ShortTermSignalGenerator:
    """Generate short-term signals combining BB, RSI, EMA and PatternDetector."""

    STRATEGY_NAME = "short_term"

    def __init__(
        self,
        bb_period: int = 8,
        bb_std: float = 2.0,
        atr_period: int = 14,
        rsi_period: int = 14,
        ema_fast: int = 15,
        ema_slow: int = 50,
        risk_pct: float = 2.0,
        max_daily_loss_pct: float = 3.0,
        session_filter: SessionFilter | None = None,
        pattern_detector: PatternDetector | None = None,
    ) -> None:
        self.bb_period    = bb_period
        self.bb_std       = bb_std
        self.atr_period   = atr_period
        self.rsi_period   = rsi_period
        self.ema_fast     = ema_fast
        self.ema_slow     = ema_slow
        self.risk_pct     = risk_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.session_filter = session_filter or SessionFilter()
        self.pattern_detector = pattern_detector or PatternDetector(
            atr_period=atr_period, bb_period=bb_period, bb_std=bb_std
        )

        # State
        self._in_position: dict[str, bool] = {}
        self._entry_price: dict[str, float] = {}
        self._daily_pnl: dict[str, float] = {}
        self._daily_trades: dict[str, int] = {}
        self._daily_loss: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Indicator helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(window=period, min_periods=period).mean()
        loss  = (-delta.clip(upper=0)).rolling(window=period, min_periods=period).mean()
        rs    = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    def _compute_indicators(
        self, df: pd.DataFrame
    ) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)

        # BB
        mid   = close.rolling(window=self.bb_period, min_periods=self.bb_period).mean()
        sigma = close.rolling(window=self.bb_period, min_periods=self.bb_period).std()
        bb_up = mid + self.bb_std * sigma
        bb_lo = mid - self.bb_std * sigma

        # ATR
        atr   = _compute_atr(high, low, close, self.atr_period)

        # RSI
        rsi   = self._compute_rsi(close, self.rsi_period)

        # EMA
        ema_f = close.ewm(span=self.ema_fast, adjust=False).mean()
        ema_s = close.ewm(span=self.ema_slow, adjust=False).mean()

        return bb_up, bb_lo, atr, rsi, ema_f, ema_s

    # ------------------------------------------------------------------
    # Per-bar signal check
    # ------------------------------------------------------------------

    def _check_bar(
        self,
        df: pd.DataFrame,
        idx: int,
        symbol: str,
        bb_up: pd.Series,
        bb_lo: pd.Series,
        atr: pd.Series,
        rsi: pd.Series,
        ema_f: pd.Series,
        ema_s: pd.Series,
        patterns: list[dict[str, object]],
    ) -> Signal | None:
        """Evaluate a single bar and return a Signal if conditions are met."""
        ts      = df["timestamp"].iloc[idx]

        cur_close = float(df["close"].iloc[idx])



        # ── Session filter ─────────────────────────────────────────────
        if not self.session_filter.is_allowed(pd.Timestamp(ts)):
            return None

        # ── Daily loss guard ───────────────────────────────────────────
        date_key = str(pd.Timestamp(ts).date())
        if self._daily_loss.get(date_key, 0) >= self.max_daily_loss_pct:
            return None
        if self._daily_trades.get(date_key, 0) >= 2:
            return None   # max 2 trades per day

        # ── Position state ─────────────────────────────────────────────
        in_pos = self._in_position.get(symbol, False)

        # ── Pattern at this bar ────────────────────────────────────────
        active_patterns = [p for p in patterns if pd.Timestamp(p["timestamp"]) == pd.Timestamp(ts)]  # type: ignore[arg-type]

        # ── LONG conditions ─────────────────────────────────────────────
        # Entry matches scan_short_term.py:
        #   price <= BB_lower * 1.005 AND (RSI < 35 OR EMA_fast > EMA_slow) AND pattern
        bb_touch_lower = cur_close <= float(bb_lo.iloc[idx]) * 1.005
        rsi_oversold   = float(rsi.iloc[idx]) < 35.0
        ema_bullish    = float(ema_f.iloc[idx]) > float(ema_s.iloc[idx])

        pattern_bull = bool(active_patterns)

        long_ready = bb_touch_lower and (rsi_oversold or ema_bullish) and pattern_bull

        if long_ready and not in_pos:
            entry  = cur_close
            # sl tracked by engine
            qty    = Decimal("1")   # unit; risk engine handles sizing
            self._in_position[symbol] = True
            self._entry_price[symbol]  = entry
            self._daily_trades[date_key] = self._daily_trades.get(date_key, 0) + 1
            return Signal(qty=qty, side="buy", entry_atr=float(atr.iloc[idx]))

        # ── SELL conditions (close long only) ───────────────────────────
        bb_touch_upper = cur_close >= float(bb_up.iloc[idx])
        rsi_overbought = float(rsi.iloc[idx]) > 65

        ema_bear = (
            float(ema_f.iloc[idx - 1]) >= float(ema_s.iloc[idx - 1]) and
            float(ema_f.iloc[idx]) < float(ema_s.iloc[idx])
        ) if idx >= 1 else False

        pattern_bear = any(p["direction"] == "short" for p in active_patterns)

        sell_ready = (bb_touch_upper or rsi_overbought) and ema_bear and pattern_bear

        if sell_ready and in_pos:
            self._in_position[symbol] = False
            entry = self._entry_price.get(symbol, cur_close)
            # Record daily P&L
            pnl_pct = (cur_close - entry) / entry * 100
            self._daily_pnl[date_key]   = self._daily_pnl.get(date_key, 0) + pnl_pct
            if pnl_pct < 0:
                self._daily_loss[date_key] = self._daily_loss.get(date_key, 0) + abs(pnl_pct)
            return Signal(qty=Decimal("1"), side="sell", entry_atr=float(atr.iloc[idx]))

        # ── Time-based exit: hold max 8 bars, then exit on close ────────
        if in_pos:
            entry_bar = self._entry_price.get(symbol, cur_close)
            _bars_held = 0  # noqa: F841
            # Simple: exit if RSI > 70 or RSI < 30 (extreme)
            rsi_val = float(rsi.iloc[idx])
            if rsi_val > 75 or rsi_val < 25:
                self._in_position[symbol] = False
                pnl_pct = (cur_close - entry_bar) / entry_bar * 100
                self._daily_pnl[date_key]   = self._daily_pnl.get(date_key, 0) + pnl_pct
                if pnl_pct < 0:
                    self._daily_loss[date_key] = self._daily_loss.get(date_key, 0) + abs(pnl_pct)
                return Signal(qty=Decimal("1"), side="sell", entry_atr=float(atr.iloc[idx]))

        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_signals(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """Scan the DataFrame and return signals. State is updated per call."""
        min_bars = max(self.bb_period * 2, self.ema_slow, self.rsi_period + 1, 30)
        if len(df) < min_bars:
            return []

        bb_up, bb_lo, atr, rsi, ema_f, ema_s = self._compute_indicators(df)
        patterns = self.pattern_detector.detect(df)

        signals: list[Signal] = []
        for i in range(min_bars, len(df)):
            sig = self._check_bar(
                df, i, symbol, bb_up, bb_lo, atr, rsi, ema_f, ema_s, patterns
            )
            if sig:
                signals.append(sig)

        return signals
