"""MiniMax OpenAI-compatible client for AI scoring.

This adapter calls MiniMax's OpenAI-compatible chat completions API and
converts the model response into the structured scoring payload expected by
`AIScorer`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.1"
DEFAULT_TIMEOUT_SECONDS = 30

_THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)


class MiniMaxAIScoringClient:
    """OpenAI-compatible MiniMax client for scoring trade candidates."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = (api_key or os.environ.get("MINIMAX_API_KEY", "")).strip() or None
        self._base_url = (
            (base_url or os.environ.get("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL)).strip()
            or DEFAULT_MINIMAX_BASE_URL
        )
        self._model = (model or os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL)).strip()
        self._timeout = (
            timeout
            if timeout is not None
            else float(os.environ.get("MINIMAX_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)).strip())
        )

    def score(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError(
                "MINIMAX_API_KEY is not set — MiniMax scoring unavailable. "
                "Set MINIMAX_API_KEY (and optionally MINIMAX_BASE_URL/MINIMAX_MODEL)."
            )

        instruction = (
            "You are a risk-aware crypto trade scoring engine. "
            "Return ONLY valid JSON with keys: "
            "ai_score (0-100 int), "
            "market_regime (trend|range|high_volatility|unknown), "
            "decision_hint (allow|allow_reduced_size|reject), "
            "risk_flags (string array), "
            "explanation (string)."
        )

        request_payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
                },
            ],
            "temperature": 0,
        }

        endpoint = f"{self._base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                endpoint,
                json=request_payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return _extract_json_object(content)


def _extract_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("MiniMax response content is not a string JSON object")

    cleaned = _THINK_TAG_PATTERN.sub("", content).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("MiniMax response did not contain a JSON object")

    candidate = cleaned[start : end + 1]
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("MiniMax response JSON is not an object")
    return parsed

