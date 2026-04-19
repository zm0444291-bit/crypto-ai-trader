"""Unit tests for MiniMaxAIScoringClient."""

from unittest.mock import MagicMock, patch

import pytest

from trading.strategies.base import TradeCandidate


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


class TestMiniMaxAIScoringClient:
    def test_raises_when_api_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        from trading.ai.minimax_client import MiniMaxAIScoringClient

        client = MiniMaxAIScoringClient()
        with pytest.raises(RuntimeError, match="MINIMAX_API_KEY is not set"):
            client.score({"candidate": {}})

    def test_parses_json_from_chat_completions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
        from trading.ai.minimax_client import MiniMaxAIScoringClient

        client = MiniMaxAIScoringClient()
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status = lambda: None
        mock_response_obj.json = lambda: {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"ai_score":82,"market_regime":"trend","decision_hint":"allow",'
                            '"risk_flags":[],"explanation":"Momentum aligned"}'
                        )
                    }
                }
            ]
        }

        with patch("trading.ai.minimax_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_response_obj
            result = client.score({"candidate": {"symbol": "BTCUSDT"}})

        assert result["ai_score"] == 82
        assert result["decision_hint"] == "allow"

    def test_parses_json_when_think_tags_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
        from trading.ai.minimax_client import MiniMaxAIScoringClient

        client = MiniMaxAIScoringClient()
        mock_response_obj = MagicMock()
        mock_response_obj.raise_for_status = lambda: None
        mock_response_obj.json = lambda: {
            "choices": [
                {
                    "message": {
                        "content": (
                            "<think>hidden reasoning</think>\n"
                            '{"ai_score":65,"market_regime":"range",'
                            '"decision_hint":"allow_reduced_size","risk_flags":["volatility"],'
                            '"explanation":"Range market"}'
                        )
                    }
                }
            ]
        }

        with patch("trading.ai.minimax_client.httpx.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value.__enter__.return_value
            mock_client.post.return_value = mock_response_obj
            result = client.score({"candidate": {"symbol": "ETHUSDT"}})

        assert result["market_regime"] == "range"
        assert result["decision_hint"] == "allow_reduced_size"


def test_ai_scorer_fail_closed_when_minimax_response_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    from trading.ai.minimax_client import MiniMaxAIScoringClient
    from trading.ai.scorer import AIScorer

    client = MiniMaxAIScoringClient()
    scorer = AIScorer(client)

    mock_response_obj = MagicMock()
    mock_response_obj.raise_for_status = lambda: None
    mock_response_obj.json = lambda: {
        "choices": [{"message": {"content": "not-json"}}],
    }

    with patch("trading.ai.minimax_client.httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_client.post.return_value = mock_response_obj
        result = scorer.score_candidate(
            candidate=_make_candidate(),
            market_context={},
            portfolio_context={},
        )

    assert result.ai_score == 0
    assert result.decision_hint == "reject"
    assert "ai_error" in result.risk_flags

