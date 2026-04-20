"""MiniMax connectivity smoke test (paper-safe).

This script only validates scoring API connectivity and response parsing.
It does not place any order or touch execution routes.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal

from trading.ai.minimax_client import MiniMaxAIScoringClient


def main() -> int:
    payload = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "timestamp": datetime.now(UTC).isoformat(),
        "candidate": {
            "direction": "long",
            "entry_reference": str(Decimal("65000")),
            "stop_reference": str(Decimal("64500")),
            "rule_confidence": str(Decimal("0.55")),
        },
        "features": {
            "ema_fast": str(Decimal("64800")),
            "ema_slow": str(Decimal("64600")),
            "rsi_14": str(Decimal("54.2")),
            "atr_14": str(Decimal("220")),
        },
    }

    try:
        result = MiniMaxAIScoringClient().score(payload)
    except Exception as exc:  # noqa: BLE001
        print(f"MiniMax smoke test FAILED: {exc}")
        return 1

    print("MiniMax smoke test OK")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
