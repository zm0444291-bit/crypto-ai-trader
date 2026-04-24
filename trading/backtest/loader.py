"""Download historical OHLCV data from Binance and persist to Parquet."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pandas as pd
import requests

from trading.backtest.store import ParquetCandleStore

# Binance API endpoints
_BASE_URL = "https://api.binance.com"
KLINES_URL = f"{_BASE_URL}/api/v3/klines"

# How many candles per request (max 1000 for Binance)
_CANDLES_PER_REQUEST = 1000

# Download directory
_DEFAULT_DOWNLOAD_DIR = Path("backtest_data/candles")


class BinanceHistoricalLoader:
    """Fetch historical candlestick (kline) data from Binance.

    Parameters
    ----------
    base_dir : str | Path
        Directory to store downloaded Parquet files.
    retry_attempts : int
        Number of times to retry on HTTP error (default 3).
    retry_delay : float
        Seconds to wait between retries (default 2.0).
    """

    def __init__(
        self,
        base_dir: str | Path = _DEFAULT_DOWNLOAD_DIR,
        retry_attempts: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.store = ParquetCandleStore(base_dir=base_dir)
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

    def download(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        force: bool = False,
    ) -> pd.DataFrame:
        """Download klines and save to Parquet.

        Parameters
        ----------
        symbol : str
            Binance symbol (e.g. "BTCUSDT").
        interval : str
            Kline interval (e.g. "15m", "1h", "1d").
        start_time : datetime
            Start of download window.
        end_time : datetime
            End of download window.
        force : bool
            Re-download even if a local parquet file already exists.

        Returns
        -------
        DataFrame with columns: timestamp, open, high, low, close, volume.

        Raises
        ------
        RuntimeError
            If all retry attempts are exhausted.
        """
        if not force and self.store.exists(symbol, interval):
            df = self.store.load(symbol, interval)
            if df is not None:
                return df

        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        all_klines: list[list[Any]] = []

        current_start = start_ms
        while current_start < end_ms:
            klines = self._fetch_with_retry(symbol, interval, current_start, end_ms)
            if not klines:
                break
            all_klines.extend(klines)
            # Advance to last fetched candle's open time + 1ms
            last_open = int(klines[-1][0])
            current_start = last_open + 1

        if not all_klines:
            df = self._empty_dataframe()
            self.store.save(symbol, interval, df)
            return df

        df = self._parse_klines(all_klines)
        self.store.save(symbol, interval, df)
        return df

    def _fetch_with_retry(
        self,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int,
    ) -> list[list[Any]]:
        """Fetch a single page of klines with retry logic."""
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": _CANDLES_PER_REQUEST,
        }
        last_error: Exception | None = None
        for _attempt in range(self.retry_attempts):
            try:
                resp = requests.get(KLINES_URL, params=params, timeout=30)
                resp.raise_for_status()
                return cast(list[list[Any]], resp.json())
            except requests.HTTPError as e:
                # Rate limit — wait longer
                if resp.status_code == 429:
                    time.sleep(self.retry_delay * 3)
                    continue
                last_error = e
                time.sleep(self.retry_delay)
            except requests.RequestException as e:
                last_error = e
                time.sleep(self.retry_delay)

        raise RuntimeError(
            f"Failed to fetch klines for {symbol} after "
            f"{self.retry_attempts} attempts: {last_error}"
        )

    def _parse_klines(self, klines: list[list[Any]]) -> pd.DataFrame:
        """Convert Binance klines list-of-lists to a typed DataFrame."""
        rows = []
        for k in klines:
            rows.append(
                {
                    "timestamp": datetime.fromtimestamp(int(k[0]) / 1000, tz=UTC),
                    "open": Decimal(str(k[1])),
                    "high": Decimal(str(k[2])),
                    "low": Decimal(str(k[3])),
                    "close": Decimal(str(k[4])),
                    "volume": Decimal(str(k[5])),
                }
            )
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def _empty_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download Binance OHLCV data to Parquet")
    parser.add_argument("symbol", help="Symbol, e.g. BTCUSDT")
    parser.add_argument(
        "--interval",
        default="15m",
        help="Kline interval (default 15m)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of past days to download (default 7)",
    )
    parser.add_argument(
        "--download-dir",
        default=str(_DEFAULT_DOWNLOAD_DIR),
        help=f"Download directory (default {_DEFAULT_DOWNLOAD_DIR})",
    )
    args = parser.parse_args()

    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)

    loader = BinanceHistoricalLoader(base_dir=args.download_dir)
    df = loader.download(args.symbol, args.interval, start, end, force=True)
    print(f"Downloaded {len(df)} candles → {loader.store._path(args.symbol, args.interval)}")
