"""Parquet-backed OHLCV candle store."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class ParquetCandleStore:
    """Read/write OHLCV candles to Parquet files.

    File layout: ``<base_dir>/<symbol>_<interval>.parquet``

    Parameters
    ----------
    base_dir : str | Path
        Root directory for parquet files. Created automatically if missing.
    """

    def __init__(self, base_dir: str | Path = "backtest_data/candles") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, symbol: str, interval: str) -> Path:
        """Return the parquet file path for a symbol/interval pair."""
        return self.base_dir / f"{symbol.lower()}_{interval}.parquet"

    def save(
        self,
        symbol: str,
        interval: str,
        df: pd.DataFrame,
    ) -> None:
        """Write a DataFrame of candles to a Parquet file.

        Parameters
        ----------
        symbol : str
            Trading symbol (e.g. "BTCUSDT").
        interval : str
            Candle interval (e.g. "15m", "1h").
        df : pd.DataFrame
            DataFrame with columns: timestamp, open, high, low, close, volume.
            timestamp must be datetime. Data is sorted by timestamp before writing.
        """
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        self._path(symbol, interval).parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(
            self._path(symbol, interval),
            compression="snappy",
            index=False,
        )

    def load(self, symbol: str, interval: str) -> pd.DataFrame | None:
        """Load candles from parquet file.

        Parameters
        ----------
        symbol : str
        interval : str

        Returns
        -------
        DataFrame with columns: timestamp, open, high, low, close, volume,
        or None if the file does not exist.
        """
        p = self._path(symbol, interval)
        if not p.exists():
            return None
        df = pd.read_parquet(p)
        # Ensure timestamp is datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)

    def exists(self, symbol: str, interval: str) -> bool:
        """Return True if the parquet file exists."""
        return self._path(symbol, interval).exists()

    def delete(self, symbol: str, interval: str) -> None:
        """Delete the parquet file if it exists (no-op if missing)."""
        p = self._path(symbol, interval)
        if p.exists():
            p.unlink()
