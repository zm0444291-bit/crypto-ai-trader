"""SessionFilter — only trade during high-probability session windows.

Gold (XAUUSD) 1h data. All timestamps UTC.

Allowed windows (UTC):
  • Asia:       00:00–08:00  (low-to-medium vol, Asian驱动)
  • London:     07:00–12:00  (high vol, directional)
  • NY Pre:    12:30–13:30  (prep for open)
  • NY Open:   13:30–20:00  (highest vol, main move)

Blocked:
  • 08:00–12:30  — London close / NY pre-data window, erratic
  • Weekend      — Saturday 00:00 onward, all Sunday
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Session windows — (start_hour, end_hour) in UTC, inclusive of start
# ---------------------------------------------------------------------------
_ALLOWED: list[tuple[int, int]] = [
    (0, 8),    # Asia: midnight–08:00
    (7, 12),   # London: 07:00–12:00
    (12, 13),  # NY Pre: 12:00–13:00 (clean up)
    (13, 20),  # NY Open: 13:00–20:00
]
_BLOCKED_HOURS: set[int] = {8, 9, 10, 11, 12}  # 08:00–12:59 blocked


class SessionFilter:
    """Filter trade signals by time-of-day session windows."""

    def __init__(self, allow_asia: bool = True, allow_london: bool = True,
                 allow_ny_pre: bool = True, allow_ny_open: bool = True) -> None:
        self.allow_asia    = allow_asia
        self.allow_london  = allow_london
        self.allow_ny_pre  = allow_ny_pre
        self.allow_ny_open = allow_ny_open

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def is_allowed(self, timestamp: pd.Timestamp) -> bool:
        """Return True if the given UTC timestamp falls in an allowed session."""
        h = timestamp.hour

        # Weekend block
        dow = timestamp.dayofweek
        if dow == 5:   # Saturday
            return False
        if dow == 6:   # Sunday (treat all as blocked until Monday)
            return False

        if h in _BLOCKED_HOURS:
            return False

        if self.allow_asia and 0 <= h < 8:
            return True
        if self.allow_london and 7 <= h < 12:
            return True   # 7–8 overlaps Asia but is also London start
        if self.allow_ny_pre and h == 12:
            return True
        if self.allow_ny_open and 13 <= h < 20:
            return True

        return False

    def is_allowed_with_context(
        self, df: pd.DataFrame, idx: int, context_bars: int = 3
    ) -> bool:
        """is_allowed + at least 2 surrounding bars are also in allowed session.

        Prevents trading the single candle that accidentally lands in a window
        while the market is actually transitioning.
        """
        if not self.is_allowed(df["timestamp"].iloc[idx]):
            return False

        # Count prior bars in same session
        allowed_count = 0
        for j in range(max(idx - context_bars, 0), idx):
            if self.is_allowed(df["timestamp"].iloc[j]):
                allowed_count += 1
        return allowed_count >= 2

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    @staticmethod
    def session_name(timestamp: pd.Timestamp) -> str:
        """Human-readable session label."""
        h = timestamp.hour
        if 0 <= h < 7:
            return "Asia_Late"
        if 7 <= h < 13:
            return "London"
        if 13 <= h < 20:
            return "NY"
        return "OffHours"

    def allowed_session_hours(self) -> list[tuple[int, int]]:
        """Return list of (start, end) hour pairs for allowed sessions."""
        return [(s, e) for s, e in _ALLOWED
                if (s == 0 and self.allow_asia) or
                   (s == 7 and self.allow_london) or
                   (s == 12 and self.allow_ny_pre) or
                   (s == 13 and self.allow_ny_open)]
