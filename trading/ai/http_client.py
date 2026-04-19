"""HTTP client for remote AI scoring service.

Configure via environment variables:
  AI_SCORING_URL        — full URL of the AI scoring endpoint (required for real scoring)
  AI_SCORING_TIMEOUT    — request timeout in seconds (default: 30)

When AI_SCORING_URL is not set, score() raises RuntimeError so that
the AIScorer falls back to its fail-closed behavior automatically.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30


class HttpAIScoringClient:
    """HTTP adapter that calls a remote AI scoring endpoint.

    The caller (AIScorer) handles all fail-closed propagation —
    this client only raises on network/transport errors.
    """

    def __init__(
        self,
        url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._url = (url or os.environ.get("AI_SCORING_URL", "")).strip() or None
        if timeout is not None:
            self._timeout = timeout
        else:
            self._timeout = float(
                os.environ.get("AI_SCORING_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)).strip()
            )

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Call the remote AI scoring endpoint.

        Raises:
            RuntimeError: if AI_SCORING_URL is not configured.
            httpx.TimeoutException: on timeout.
            httpx.HTTPStatusError: on non-2xx HTTP response.
            httpx.HTTPError: on other transport errors.
        """
        if not self._url:
            raise RuntimeError(
                "AI_SCORING_URL is not set — AI scoring unavailable. "
                "Set the environment variable to enable remote scoring."
            )

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                self._url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
