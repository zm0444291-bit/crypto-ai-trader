"""Unit tests for market data ingestion runner."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch


class TestIngestOnce:
    """ingest_once fetches klines and upserts them via CandlesRepository."""

    def test_fetches_and_upserts_for_all_symbol_timeframe_pairs(self) -> None:
        from trading.market_data.ingestion_runner import ingest_once

        fake_candle = MagicMock(
            symbol="BTCUSDT",
            timeframe="15m",
            open_time=datetime(2026, 4, 19, 1, 0, tzinfo=UTC),
            close_time=datetime(2026, 4, 19, 1, 15, tzinfo=UTC),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.5"),
            volume=Decimal("1.0"),
            source="binance",
        )

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.upsert_many.return_value = 1
        mock_events = MagicMock()

        with patch(
            "trading.market_data.ingestion_runner.BinanceKlineClient"
        ) as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.fetch_klines.return_value = [fake_candle]

            with patch(
                "trading.market_data.ingestion_runner.CandlesRepository",
                return_value=mock_repo,
            ):
                with patch(
                    "trading.market_data.ingestion_runner.EventsRepository",
                    return_value=mock_events,
                ):
                    counts = ingest_once(
                        mock_session, symbols=["BTCUSDT"], timeframes=["15m"]
                    )

        assert counts == {"BTCUSDT/15m": 1}
        mock_client_instance.fetch_klines.assert_called_once_with(
            "BTCUSDT", "15m", limit=100
        )
        mock_repo.upsert_many.assert_called_once()
        mock_events.record_event.assert_called_once()

    def test_continues_on_fetch_error_for_single_symbol(self) -> None:
        from trading.market_data.ingestion_runner import ingest_once

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.upsert_many.return_value = 0
        mock_events = MagicMock()

        with patch(
            "trading.market_data.ingestion_runner.BinanceKlineClient"
        ) as MockClient:
            mock_client_instance = MockClient.return_value
            mock_client_instance.fetch_klines.side_effect = [
                RuntimeError("network error"),
                [],  # ETHUSDT succeeds with 0 candles
            ]

            with patch(
                "trading.market_data.ingestion_runner.CandlesRepository",
                return_value=mock_repo,
            ):
                with patch(
                    "trading.market_data.ingestion_runner.EventsRepository",
                    return_value=mock_events,
                ):
                    counts = ingest_once(
                        mock_session,
                        symbols=["BTCUSDT", "ETHUSDT"],
                        timeframes=["15m"],
                    )

        assert counts["BTCUSDT/15m"] == 0
        assert mock_events.record_event.called


class TestIngestLoop:
    """ingest_loop runs ingest_once on an interval and respects stop/max_cycles."""

    def test_stops_after_max_cycles(self) -> None:
        from trading.market_data.ingestion_runner import ingest_loop

        mock_factory = MagicMock()
        mock_session = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "trading.market_data.ingestion_runner.ingest_once"
        ) as mock_ingest:
            with patch("trading.market_data.ingestion_runner.EventsRepository"):
                mock_ingest.return_value = {}

                stop_event = MagicMock()
                stop_event.is_set.return_value = False

                cycles = ingest_loop(
                    interval_seconds=1,
                    session_factory=mock_factory,
                    max_cycles=2,
                    stop_event=stop_event,
                )

        assert cycles == 2
        assert mock_ingest.call_count == 2

    def test_records_started_and_stopped_events(self) -> None:
        from trading.market_data.ingestion_runner import ingest_loop

        mock_factory = MagicMock()
        mock_session = MagicMock()
        mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_factory.return_value.__exit__ = MagicMock(return_value=False)

        with patch(
            "trading.market_data.ingestion_runner.ingest_once"
        ) as mock_ingest:
            with patch(
                "trading.market_data.ingestion_runner.EventsRepository"
            ) as mock_events_cls:
                mock_ingest.return_value = {}

                stop_event = MagicMock()
                stop_event.is_set.return_value = False

                ingest_loop(
                    interval_seconds=10,
                    session_factory=mock_factory,
                    max_cycles=1,
                    stop_event=stop_event,
                )

        # ingest_loop should have called EventsRepository at start and stop
        assert mock_events_cls.return_value.record_event.call_count >= 2

