"""
RiskFilter — risk management layer that validates and adjusts signals
from the StrategyAllocator before they reach the execution engine.

Filters:
  1. Economic calendar (FOMC / NFP / CPI) — reduce or block trades around events
  2. Volatility cap — if ATR% > 90th percentile, reduce position size
  3. Cross-asset confirmation — DXY, US10Y yield for XAUUSD confirmation
  4. Consecutive loss cap — after N consecutive losses, reduce position size
  5. Daily loss cap — if daily PnL < -X%, block new entries for the day
  6. Weekend filter — no new entries on Friday after 17:00 UTC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypedDict

import yaml


class FilterAction(TypedDict):
    allowed: bool
    reason: str
    position_multiplier: float  # 0.0 = blocked, 0.5 = half size, 1.0 = full


@dataclass
class RiskFilterConfig:
    """Configuration for risk filters."""
    # Event window (hours before/after to reduce activity)
    event_window_before_hours: float = 2.0
    event_window_after_hours: float = 1.0
    # Position multipliers during high vol / events
    event_multiplier: float = 0.25  # 25% of normal size around events
    high_vol_multiplier: float = 0.5  # 50% of normal size in high vol
    # Loss streaks
    consecutive_loss_cap: int = 3  # reduce after this many consecutive losses
    loss_streak_multiplier: float = 0.5  # 50% size after loss streak
    # Daily loss
    daily_loss_cap_pct: float = 0.03  # 3% daily loss → block new entries
    # ATR percentile above which we consider "high volatility"
    atr_high_pct: float = 0.80


@dataclass
class EconomicEvent:
    """A scheduled economic event."""
    name: str
    timestamp: datetime
    impact: str  # "high", "medium", "low"


@dataclass
class RiskFilter:
    """Risk filter layer."""

    config: RiskFilterConfig = field(default_factory=RiskFilterConfig)
    _events: list[EconomicEvent] = field(default_factory=list)

    # Internal state
    _consecutive_losses: int = 0
    _daily_pnl: float = 0.0
    _daily_start_equity: float = 1.0
    _last_trade_date: str = ""  # YYYY-MM-DD

    def load_economic_calendar(self, path: str) -> None:
        """Load events from YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self._events = []
        for item in data.get("events", []):
            self._events.append(EconomicEvent(
                name=item["name"],
                timestamp=datetime.fromisoformat(item["timestamp"]),
                impact=item.get("impact", "medium"),
            ))

    def filter_signal(
        self,
        side: str,  # BUY / SELL / FLAT
        confidence: float,
        max_position_pct: float,
        atr_pct_rank: float,
        current_time: datetime | None = None,
    ) -> FilterAction:
        """
        Validate and potentially adjust a signal.

        Returns FilterAction with:
          allowed: bool — can this trade proceed?
          reason: str — why blocked or adjusted?
          position_multiplier: float — size adjustment (0=blocked, 0.5=half, 1=full)
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        position_multiplier = 1.0
        reasons: list[str] = []
        allowed = True

        # ── 1. Event filter ───────────────────────────────────────────────────
        event_block = self._is_event_window(current_time)
        if event_block:
            position_multiplier *= self.config.event_multiplier
            reasons.append(f"event:{event_block.name}")

        # ── 2. Volatility cap ────────────────────────────────────────────────
        if atr_pct_rank >= self.config.atr_high_pct:
            position_multiplier *= self.config.high_vol_multiplier
            reasons.append(f"high_vol(atr_pct={atr_pct_rank:.0%})")

        # ── 3. Daily loss cap ───────────────────────────────────────────────
        today = current_time.strftime("%Y-%m-%d")
        if today != self._last_trade_date:
            # New day — reset daily tracking
            self._daily_pnl = 0.0
            self._last_trade_date = today

        if self._daily_pnl < -self.config.daily_loss_cap_pct:
            allowed = False
            reasons.append(f"daily_loss_cap({self._daily_pnl:.1%})")
            position_multiplier = 0.0

        # ── 4. Consecutive loss cap ─────────────────────────────────────────
        if self._consecutive_losses >= self.config.consecutive_loss_cap:
            position_multiplier *= self.config.loss_streak_multiplier
            reasons.append(f"loss_streak({self._consecutive_losses})")

        # ── 5. Weekend filter ───────────────────────────────────────────────
        if current_time.weekday() == 4 and current_time.hour >= 17:
            # Friday after 17:00 UTC
            allowed = False
            reasons.append("weekend")
            position_multiplier = 0.0

        # ── 6. Flat signal ─────────────────────────────────────────────────
        if side == "FLAT":
            allowed = False
            reasons.append("flat_signal")
            position_multiplier = 0.0

        reason_str = "; ".join(reasons) if reasons else "pass"

        return FilterAction(
            allowed=allowed,
            reason=reason_str,
            position_multiplier=max(0.0, min(1.0, position_multiplier)),
        )

    def record_trade_result(self, won: bool, pnl_pct: float) -> None:
        """Called after a trade closes to update risk state."""
        if won:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
        self._daily_pnl += pnl_pct

    def reset_daily(self, equity: float) -> None:
        """Reset daily tracking (called at start of new day)."""
        self._daily_pnl = 0.0
        self._daily_start_equity = equity

    def _is_event_window(self, dt: datetime) -> EconomicEvent | None:
        """Check if we're in a high-impact event window."""
        window = self.config.event_window_before_hours
        for event in self._events:
            diff_hours = (event.timestamp - dt).total_seconds() / 3600
            if -self.config.event_window_after_hours <= diff_hours <= window:
                if event.impact == "high":
                    return event
        return None
