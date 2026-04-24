"""PatternDetector — short-term pattern recognition for gold (XAUUSD) 1h data.

Patterns:
  1. AsianSessionReversal — Asia-driven trend reversed at London open.
  2. NYSessionBreakout     — tight-range compression broken at NY open.
  3. ATRCompression        — consecutive ATR contraction signals explosion.
  4. RoundNumberTrap       — price hits round level then reverses.

All timestamps are UTC. DataFrame columns: timestamp, open, high, low, close, volume.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants — session windows (UTC hour)
# ---------------------------------------------------------------------------
_ASIA_START    = 0    # 00:00 UTC
_ASIA_END      = 8    # 08:00 UTC
_NY_OPEN_HOURS = (13, 14)   # 13:30–14:30 window

# Detection thresholds
_COMPRESSION_CANDLES = 5
_ATR_COMPRESS_RATIO  = 0.80   # ATR < 80% of 5-candle ATR avg
_TIGHT_ATR_RATIO     = 0.50   # ATR < 50% of 20-candle ATR avg
_TIGHT_CANDLE_COUNT  = 4
_ROUND_PCT           = 0.002  # within 0.2% of round number


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """True Range = max(high-low, |high-prev_close|, |low-prev_close|)."""
    prev = close.shift(1)
    tr1  = high - low
    tr2  = (high - prev).abs()
    tr3  = (low - prev).abs()
    tr   = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def _compute_bb(
    close: pd.Series, period: int = 20, nb_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (middle, upper, lower) Bollinger bands."""
    mid = close.rolling(window=period, min_periods=period).mean()
    sigma = close.rolling(window=period, min_periods=period).std()
    return mid, mid + nb_std * sigma, mid - nb_std * sigma


def _bb_bandwidth(upper: pd.Series, lower: pd.Series, middle: pd.Series) -> pd.Series:
    return (upper - lower) / middle


def _hour(ts: pd.Timestamp | pd.DatetimeIndex) -> int:
    return ts.hour  # type: ignore[return-value]


def _is_asia_candle(ts: pd.Timestamp) -> bool:
    h = _hour(ts)
    return _ASIA_START <= h < _ASIA_END


def _is_ny_open(ts: pd.Timestamp) -> bool:
    return _hour(ts) in _NY_OPEN_HOURS


def _near_round(price: float) -> bool:
    """Within 0.2% of a round 100-level (2600, 2700, … 4900 for gold)."""
    if price <= 0:
        return False
    rounded = round(price / 100) * 100
    return abs(price - rounded) / price <= _ROUND_PCT


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

PatternDict = dict[str, object]


# ---------------------------------------------------------------------------
# PatternDetector
# ---------------------------------------------------------------------------

class PatternDetector:
    """Detect 4 short-term OHLCV patterns on 1h XAUUSD data."""

    def __init__(
        self,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
    ) -> None:
        self.atr_period = atr_period
        self.bb_period  = bb_period
        self.bb_std     = bb_std

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, df: pd.DataFrame) -> list[PatternDict]:
        """Return detected pattern dicts in the DataFrame.

        Each dict: {pattern_type, direction, timestamp, strength (0–1)}
        """
        min_bars = max(self.bb_period * 2, self.atr_period * 2, _COMPRESSION_CANDLES + 5)
        if len(df) < min_bars:
            return []

        close  = df["close"].astype(float)
        high   = df["high"].astype(float)
        low    = df["low"].astype(float)
        # volume reserved for future use
        _vol = df["volume"].astype(float)
        ts     = df["timestamp"]

        atr    = _compute_atr(high, low, close, self.atr_period)
        bb_mid, bb_up, bb_lo = _compute_bb(close, self.bb_period, self.bb_std)
        bb_bw   = _bb_bandwidth(bb_up, bb_lo, bb_mid)

        results: list[PatternDict] = []

        for i in range(min_bars, len(df)):

            p1 = self._asian_reversal(i, df, close, bb_up, bb_lo, atr, ts)
            if p1:
                results.append(p1)

            p2 = self._ny_breakout(i, df, close, high, low, atr, ts)
            if p2:
                results.append(p2)

            p3 = self._atr_compression(i, df, atr, bb_bw, ts)
            if p3:
                results.append(p3)

            p4 = self._round_trap(i, df, close, ts)
            if p4:
                results.append(p4)

        return results

    # ------------------------------------------------------------------
    # Pattern 1 — AsianSessionReversal
    # ------------------------------------------------------------------

    def _asian_reversal(
        self,
        idx: int,
        df: pd.DataFrame,
        close: pd.Series,
        bb_up: pd.Series,
        bb_lo: pd.Series,
        atr: pd.Series,
        ts: pd.Series,
    ) -> PatternDict | None:
        """Asia session (00:00–08:00 UTC) builds a BB extreme; London open reverses.

        Detection:
          - Last 3 Asia candles: price at BB upper OR lower on every candle.
          - Current candle is in London open window (07:00–09:00 UTC).
          - Current candle opens HIGHER than prior Asia candle close (for longs)
            or LOWER (for shorts) — candle direction reverses.
        """
        cur_h = _hour(ts.iloc[idx])
        if not (7 <= cur_h <= 9):  # London open window
            return None

        # Collect last 3 Asia candles
        asia: list[int] = []
        for j in range(idx - 1, max(idx - 20, -1), -1):
            if _is_asia_candle(ts.iloc[j]):
                asia.append(j)
            if len(asia) == 3:
                break
        if len(asia) != 3:
            return None

        up_hits = [close.iloc[j] >= bb_up.iloc[j] for j in asia]
        dn_hits = [close.iloc[j] <= bb_lo.iloc[j] for j in asia]

        if not (all(up_hits) or all(dn_hits)):
            return None

        prev_close = close.iloc[asia[-1]]
        cur_open   = df["open"].iloc[idx].astype(float)

        if all(dn_hits):
            # Was at lower BB → expect bullish reversal
            if cur_open <= prev_close:
                return None
            direction: Literal["long", "short"] = "long"
        else:
            # Was at upper BB → expect bearish reversal
            if cur_open >= prev_close:
                return None
            direction = "short"

        # Strength: BB deviation + volume
        deviations = [abs(close.iloc[j] - bb_lo.iloc[j]) / (bb_up.iloc[j] - bb_lo.iloc[j]) for j in asia]
        vols       = [float(df["volume"].iloc[j]) for j in asia]
        strength    = self._scale_strength(deviations, vols)

        return dict(
            pattern_type="AsianSessionReversal",
            direction=direction,
            timestamp=ts.iloc[idx],
            strength=strength,
        )

    # ------------------------------------------------------------------
    # Pattern 2 — NYSessionBreakout
    # ------------------------------------------------------------------

    def _ny_breakout(
        self,
        idx: int,
        df: pd.DataFrame,
        close: pd.Series,
        high: pd.Series,
        low: pd.Series,
        atr: pd.Series,
        ts: pd.Series,
    ) -> PatternDict | None:
        """NY open (13:30–14:30 UTC) breaks tight-range compression.

        Detection:
          - 4+ consecutive candles with ATR < 50% of its 20-candle average.
          - Candle at 13:00/14:00 breaks above (bullish) or below (bearish)
            the tight range high/low.
        """
        if not _is_ny_open(ts.iloc[idx]):
            return None

        tight_count = 0
        for j in range(idx - 1, max(idx - 20, -1), -1):
            avg_20 = atr.iloc[j:j + 1].mean() if j < len(atr) - 1 else atr.iloc[j]
            if atr.iloc[j] < _TIGHT_ATR_RATIO * avg_20:
                tight_count += 1
            else:
                break
        if tight_count < _TIGHT_CANDLE_COUNT:
            return None

        cstart    = idx - tight_count
        tight_hi  = high.iloc[cstart:idx].max()
        tight_lo  = low.iloc[cstart:idx].min()

        cur_open  = df["open"].iloc[idx].astype(float)
        cur_close = close.iloc[idx]

        direction: Literal["long", "short"]
        if cur_close > tight_hi and cur_open <= tight_hi:
            direction = "long"
        elif cur_close < tight_lo and cur_open >= tight_lo:
            direction = "short"
        else:
            return None

        avg_atr_20 = atr.iloc[cstart:idx].mean()
        atr_ratio  = atr.iloc[idx] / (avg_atr_20 + 1e-9)
        strength   = float(np.clip(1.0 - atr_ratio * 2, 0.1, 1.0))

        return dict(
            pattern_type="NYSessionBreakout",
            direction=direction,
            timestamp=ts.iloc[idx],
            strength=strength,
        )

    # ------------------------------------------------------------------
    # Pattern 3 — ATRCompression
    # ------------------------------------------------------------------

    def _atr_compression(
        self,
        idx: int,
        df: pd.DataFrame,
        atr: pd.Series,
        bb_bw: pd.Series,
        ts: pd.Series,
    ) -> PatternDict | None:
        """5 candles with shrinking ATR + BB bandwidth narrowing → explosion.

        Detection:
          - 5 consecutive candles where ATR < 80% of the 5-candle ATR average.
          - BB bandwidth also contracting over the same window.
          - Direction inferred from the break candle.
        """
        if idx < _COMPRESSION_CANDLES:
            return None

        cstart    = idx - _COMPRESSION_CANDLES + 1
        avg_atr_5 = atr.iloc[cstart:idx + 1].mean()

        compressed = all(
            atr.iloc[j] < _ATR_COMPRESS_RATIO * avg_atr_5
            for j in range(cstart, idx + 1)
        )
        if not compressed:
            return None

        if not (bb_bw.iloc[idx] < bb_bw.iloc[cstart]):
            return None

        cur_open   = df["open"].iloc[idx].astype(float)
        cur_close  = df["close"].iloc[idx].astype(float)

        if cur_close > cur_open:
            direction: Literal["long", "short"] = "long"
        elif cur_close < cur_open:
            direction = "short"
        else:
            return None

        atr_contraction = avg_atr_5 / (atr.iloc[idx] + 1e-9)
        bw_contraction  = bb_bw.iloc[cstart] / (bb_bw.iloc[idx] + 1e-9)
        strength = float(np.clip((atr_contraction + bw_contraction) / 20, 0.1, 1.0))

        return dict(
            pattern_type="ATRCompression",
            direction=direction,
            timestamp=ts.iloc[idx],
            strength=strength,
        )

    # ------------------------------------------------------------------
    # Pattern 4 — RoundNumberTrap
    # ------------------------------------------------------------------

    def _round_trap(
        self,
        idx: int,
        df: pd.DataFrame,
        close: pd.Series,
        ts: pd.Series,
    ) -> PatternDict | None:
        """Price approaches round 100-level (0.2%) then reverses.

        Detection:
          - Current and previous close both within 0.2% of same round level.
          - Current candle reverses direction relative to prior candle.
        """
        if idx < 1:
            return None

        cur_close  = float(close.iloc[idx])
        prev_close = float(close.iloc[idx - 1])

        if not (_near_round(cur_close) and _near_round(prev_close)):
            return None

        # Same round number (within 0.1%)
        if abs(cur_close - prev_close) / (cur_close + 1e-9) > 0.001:
            return None

        cur_open  = float(df["open"].iloc[idx])
        prev_open = float(df["open"].iloc[idx - 1])

        direction: Literal["long", "short"]
        if prev_close > prev_open and cur_close < cur_open:
            direction = "short"   # topped out, reversed down
        elif prev_close < prev_open and cur_close > cur_open:
            direction = "long"    # bottomed out, reversed up
        else:
            return None

        rounded   = round(cur_close / 100) * 100
        proximity = 1.0 - abs(cur_close - rounded) / (cur_close * _ROUND_PCT + 1e-9)
        strength  = float(np.clip(proximity, 0.1, 1.0))

        return dict(
            pattern_type="RoundNumberTrap",
            direction=direction,
            timestamp=ts.iloc[idx],
            strength=strength,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scale_strength(bb_deviations: list[float], volumes: list[float]) -> float:
        """Normalise strength to [0.1, 1.0] from BB deviation and volume lists."""
        dev_arr = np.array(bb_deviations, dtype=float)
        vol_arr = np.array(volumes, dtype=float)

        dev_score = float(np.mean(dev_arr))  # 0 = at middle, 1 = at band
        vol_score = float(np.clip(vol_arr.mean() / (vol_arr.max() + 1e-9), 0, 1))
        combined  = dev_score * 0.7 + vol_score * 0.3
        return float(np.clip(combined, 0.1, 1.0))
