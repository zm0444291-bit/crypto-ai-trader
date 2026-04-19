"""Unit tests for HttpAIScoringClient."""

from unittest.mock import patch

import pytest

from trading.strategies.base import TradeCandidate


class TestHttpAIScoringClientMissingUrl:
    """When AI_SCORING_URL is absent, score() raises RuntimeError."""

    def test_raises_when_url_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_SCORING_URL", raising=False)
        from trading.ai.http_client import HttpAIScoringClient

        client = HttpAIScoringClient()
        with pytest.raises(RuntimeError, match="AI_SCORING_URL is not set"):
            client.score({"candidate": {}})

    def test_raises_when_url_is_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_SCORING_URL", "")
        from trading.ai.http_client import HttpAIScoringClient

        client = HttpAIScoringClient()
        with pytest.raises(RuntimeError, match="AI_SCORING_URL is not set"):
            client.score({"candidate": {}})


class TestHttpAIScoringClientValidResponse:
    """When URL is set and server returns 200, score() returns parsed JSON."""

    def test_returns_parsed_json_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_SCORING_URL", "https://ai.example.com/score")

        from trading.ai.http_client import HttpAIScoringClient

        client = HttpAIScoringClient()

        mock_response = {
            "ai_score": 82,
            "market_regime": "trend",
            "decision_hint": "allow",
            "risk_flags": [],
            "explanation": "Momentum is strong.",
        }

        with patch("trading.ai.http_client.httpx.post") as mock_post:
            mock_post.return_value.__enter__ = lambda s: s
            mock_post.return_value.__exit__ = lambda *a: None
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json = lambda: mock_response

            result = client.score({"candidate": {}})

        assert result == mock_response


class TestHttpAIScoringClientErrors:
    """Network/transport errors are raised and handled by AIScorer fail-closed."""

    def test_timeout_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        monkeypatch.setenv("AI_SCORING_URL", "https://ai.example.com/score")

        from trading.ai.http_client import HttpAIScoringClient

        client = HttpAIScoringClient()

        with patch("trading.ai.http_client.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(httpx.TimeoutException):
                client.score({"candidate": {}})

    def test_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests

        monkeypatch.setenv("AI_SCORING_URL", "https://ai.example.com/score")

        from trading.ai.http_client import HttpAIScoringClient

        client = HttpAIScoringClient()

        with patch("trading.ai.http_client.httpx.post") as mock_post:
            mock_post.side_effect = requests.HTTPError("500 Server Error")

            with pytest.raises(requests.HTTPError):
                client.score({"candidate": {}})


class TestHttpAIScoringClientAiscoreIntegration:
    """HttpAIScoringClient wired into AIScorer fail-closed path."""

    def test_aiscorer_fail_closed_when_url_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AI_SCORING_URL", raising=False)

        from trading.ai.http_client import HttpAIScoringClient
        from trading.ai.scorer import AIScorer

        client = HttpAIScoringClient()
        scorer = AIScorer(client)

        result = scorer.score_candidate(
            candidate=_make_candidate(),
            market_context={},
            portfolio_context={},
        )

        # AIScorer must fall closed when client raises
        assert result.ai_score == 0
        assert result.decision_hint == "reject"
        assert "ai_error" in result.risk_flags

    def test_aiscorer_fail_closed_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        monkeypatch.setenv("AI_SCORING_URL", "https://ai.example.com/score")

        from trading.ai.http_client import HttpAIScoringClient
        from trading.ai.scorer import AIScorer

        client = HttpAIScoringClient()
        scorer = AIScorer(client)

        with patch("trading.ai.http_client.httpx.post") as mock_post:
            mock_post.side_effect = httpx.TimeoutException("timed out")

            result = scorer.score_candidate(
                candidate=_make_candidate(),
                market_context={},
                portfolio_context={},
            )

        assert result.ai_score == 0
        assert result.decision_hint == "reject"
        assert "ai_error" in result.risk_flags


def _make_candidate() -> TradeCandidate:
    from datetime import UTC, datetime
    from decimal import Decimal

    return TradeCandidate(
        strategy_name="multi_timeframe_momentum",
        symbol="BTCUSDT",
        side="BUY",
        entry_reference=Decimal("100"),
        stop_reference=Decimal("96"),
        rule_confidence=Decimal("0.70"),
        reason="Momentum aligned.",
        created_at=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
    )
