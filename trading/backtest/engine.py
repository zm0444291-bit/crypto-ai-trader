"""Backtest engine — event-driven historical simulation.

The engine runs a strategy against historical OHLCV data (loaded from
ParquetCandleStore) and produces a BacktestResult with performance metrics.
Execution uses next-bar-open pricing to avoid look-ahead bias.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from trading.portfolio.accounting import PortfolioAccount, Position

if TYPE_CHECKING:
    from trading.backtest.store import ParquetCandleStore


def _ensure_utc(dt: datetime) -> datetime:
    """Return a UTC-aware datetime, localising naive datetimes to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class BacktestConfig:
    """Configuration for a backtest run.

    Attributes
    ----------
    fee_bps : Decimal
        Trading fee in basis points per side (e.g. Decimal("10") = 0.10% per trade).
    slippages : dict[str, Decimal]
        Per-symbol additional slippage in bps added to entry/exit.
        Unknown symbols fall back to slippages["default"].
    initial_equity : Decimal
        Starting portfolio equity in USDT.
    risk_per_trade_pct : Decimal
        Fraction of equity risked per trade (e.g. Decimal("0.02") = 2%).
    """

    fee_bps: Decimal = field(default=Decimal("10"))
    slippages: dict[str, Decimal] = field(default_factory=lambda: {"default": Decimal("0")})
    initial_equity: Decimal = field(default=Decimal("100_000"))
    risk_per_trade_pct: Decimal = field(default=Decimal("2"))
    interval: str = field(default="1h")


@dataclass
class BacktestResult:
    """Results from a backtest run.

    Attributes
    ----------
    strategy_name : str
        Name of the strategy run.
    symbols : list[str]
        Symbols traded.
    start_time : datetime
        Backtest start (first bar open time).
    end_time : datetime
        Backtest end (last bar close time).
    initial_equity : Decimal
        Starting equity.
    final_equity : Decimal
        Ending equity after all trades.
    total_return_pct : Decimal
        Total return as a percentage (e.g. Decimal("5.0") = 5%).
    sharpe_ratio : float
        Annualised Sharpe ratio (assuming 15m bars = 35040 bars/year).
    max_drawdown_pct : Decimal
        Maximum drawdown as a percentage of equity peak.
    win_rate : Decimal
        Fraction of winning trades (0..1).
    avg_win_loss_ratio : Decimal
        Average win / average loss.
    total_trades : int
        Total number of round-trip trades executed.
    monthly_returns : dict[str, Decimal]
        Map of "YYYY-MM" → return percentage for that month.
    equity_curve : list[tuple[datetime, Decimal]]
        Equity at each bar timestamp.
    trades : list[dict[str, Any]]
        Detailed log of each executed trade.
    """

    strategy_name: str
    symbols: list[str]
    start_time: datetime
    end_time: datetime
    initial_equity: Decimal
    final_equity: Decimal
    total_return_pct: Decimal
    sharpe_ratio: float
    max_drawdown_pct: Decimal
    win_rate: Decimal
    total_trades: int
    avg_win_loss_ratio: Decimal
    avg_win: Decimal = Decimal(0)
    avg_loss: Decimal = Decimal(0)
    monthly_returns: dict[str, Decimal] = field(default_factory=dict)
    equity_curve: list[tuple[datetime, Decimal]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)


class BacktestEngine:
    """Event-driven backtesting engine.

    Parameters
    ----------
    config : BacktestConfig
        Backtest configuration (fees, slippage, equity).
    store : ParquetCandleStore
        Historical OHLCV data store.

    Notes
    -----
    **Signal → Position lifecycle:**
    1. Strategy generates a signal at bar t (close of bar t).
    2. Engine executes at bar t+1 open price ± slippage.
    3. Fee is deducted on both entry and exit.

    This ensures no look-ahead bias: signals cannot use bar t's OHLCV
    to generate a trade that would have executed at bar t's close.
    """

    BARS_PER_YEAR = 35_040  # 15-minute bars × 35040 ≈ 1 year

    def __init__(self, config: BacktestConfig, store: "ParquetCandleStore") -> None:
        self.config = config
        self.store = store

    def run(
        self,
        strategy: Any,  # duck-typed: needs generate_signals(symbol, df) -> list[Signal]
        symbols: list[str],
        start_time: datetime,
        end_time: datetime,
        initial_equity: Decimal | None = None,
    ) -> BacktestResult:
        """Run the backtest.

        Parameters
        ----------
        strategy : object
            Strategy object with a ``generate_signals(symbol, df)`` method.
            Returns a list of Signal namedtuples (qty, side, price_type).
        symbols : list[str]
            Symbols to run.
        start_time : datetime
            Backtest start (inclusive).
        end_time : datetime
            Backtest end (inclusive).
        initial_equity : Decimal | None
            Override config.initial_equity if provided.

        Returns
        -------
        BacktestResult
        """
        equity = initial_equity if initial_equity is not None else self.config.initial_equity

        # ── 1. Load data ──────────────────────────────────────────────────────
        # Normalise query times to UTC-aware so they can compare with tz-aware
        # DataFrame timestamps without a TypeError.
        _start = _ensure_utc(start_time)
        _end = _ensure_utc(end_time)

        data: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.store.load(sym, self.config.interval)
            if df is None or df.empty:
                continue
            df = df[(df["timestamp"] >= _start) & (df["timestamp"] <= _end)]
            if not df.empty:
                data[sym] = df

        if not data:
            raise ValueError("No data loaded for the given symbols and time range")

        # ── 2. Build unified timeline (all symbols, sorted) ───────────────────
        all_ts: set[datetime] = set()
        for df in data.values():
            all_ts.update(df["timestamp"].tolist())
        timeline = sorted(all_ts)

        # ── 3. Initialise portfolio ───────────────────────────────────────────
        portfolio = PortfolioAccount(cash_balance=equity)
        positions: dict[str, Position] = {}
        equity_curve: list[tuple[datetime, Decimal]] = []
        trades: list[dict[str, Any]] = []

        # ── 4. Iterate bars ──────────────────────────────────────────────────
        for _i, ts in enumerate(timeline):
            for sym in symbols:
                if sym not in data:
                    continue
                # Look up current bar by index position rather than filtering
                # by timestamp (which can miss bars due to tz-aware comparison).
                # df is already sorted by timestamp when loaded from store.
                df = data[sym]
                idx_list = df.index[df["timestamp"] == ts].tolist()
                if not idx_list:
                    continue
                idx = idx_list[0]
                assert df is not None
                bar_open = Decimal(str(df.at[idx, "open"]))
                bar_close = Decimal(str(df.at[idx, "close"]))

                # ── Signal generation ─────────────────────────────────────────
                # Use all bars up to (and including) this bar for signal
                bars_up_to_t = df[df["timestamp"] <= ts]
                try:
                    signals = strategy.generate_signals(sym, bars_up_to_t)
                except Exception:
                    signals = []

            for sig in signals:
                    pos = positions.get(sym)
                    slip = self._slippage(sym)

                    if sig.side == "buy" and pos is None:
                        # ── Entry ────────────────────────────────────────────
                        notional = portfolio.cash_balance * Decimal("0.95")
                        if notional <= Decimal("0"):
                            continue
                        # Execute at NEXT bar's open (bar_{t+1}) to avoid look-ahead
                        next_idx = idx + 1
                        if next_idx >= len(df):
                            continue
                        next_open = Decimal(str(df.iloc[next_idx]["open"]))
                        # Convert bps to fraction: 5 bps → 0.0005
                        entry_price = next_open * (Decimal("1") + slip / Decimal("10000"))
                        fee_bps = self.config.fee_bps
                        qty = notional / entry_price
                        fee = entry_price * qty * fee_bps / Decimal("10000")
                        cost = entry_price * qty + fee
                        portfolio.cash_balance -= cost
                        positions[sym] = Position(
                            symbol=sym,
                            qty=qty,
                            avg_entry_price=entry_price,
                            fees_paid_usdt=fee,
                            opened_at=ts,
                            entry_atr=getattr(sig, "entry_atr", None),
                        )

                        trades.append(
                            {
                                "symbol": sym,
                                "side": "buy",
                                "entry_price": entry_price,
                                "qty": qty,
                                "fee": fee,
                                "timestamp": df.iloc[next_idx]["timestamp"],
                            }
                        )

                    elif sig.side == "sell" and pos is not None:
                        # ── Exit ─────────────────────────────────────────────
                        next_idx = idx + 1
                        if next_idx >= len(df):
                            continue
                        next_open = Decimal(str(df.iloc[next_idx]["open"]))
                        exit_price = next_open * (Decimal("1") - slip / Decimal("10000"))
                        exit_qty = pos.qty
                        fee = exit_price * exit_qty * self.config.fee_bps / Decimal("10000")
                        gross = exit_price * exit_qty - fee
                        pnl = (
                            (exit_price - pos.avg_entry_price) * exit_qty
                            - pos.fees_paid_usdt
                            - fee
                        )

                        is_win = pnl > 0
                        trades.append(
                            {
                                "symbol": sym,
                                "side": "sell",
                                "exit_price": exit_price,
                                "qty": exit_qty,
                                "fee": fee,
                                "pnl": pnl,
                                "is_win": is_win,
                                "timestamp": df.iloc[next_idx]["timestamp"],
                            }
                        )
                        portfolio.cash_balance += gross

                        del positions[sym]

            # End of bar: record equity (positions reflect this bar's close)
            total_val = self._portfolio_value(portfolio, positions, data, at_ts=ts)
            equity_curve.append((ts, total_val))

        # ── 5. Close open positions at final bar close ────────────────────────
        final_ts = timeline[-1] if timeline else end_time
        for sym, pos in list(positions.items()):
            if sym not in data:
                continue
            df = data[sym]
            close_price = Decimal(str(df.iloc[-1]["close"]))
            slip = self._slippage(sym)
            exit_price = close_price * (Decimal("1") - slip / Decimal("10000"))
            fee = exit_price * pos.qty * self.config.fee_bps / Decimal("10000")
            gross = exit_price * pos.qty - fee
            pnl = (exit_price - pos.avg_entry_price) * pos.qty - pos.fees_paid_usdt - fee
            trades.append(
                {
                    "symbol": sym,
                    "side": "sell",
                    "exit_price": exit_price,
                    "qty": pos.qty,
                    "fee": fee,
                    "pnl": pnl,
                    "is_win": pnl > 0,
                    "timestamp": final_ts,
                }
            )
            portfolio.cash_balance += gross
            del positions[sym]

        # ── 6. Compute metrics ────────────────────────────────────────────────
        final_equity = self._portfolio_value(portfolio, positions, data)
        total_return_pct = (
            ((final_equity - equity) / equity * 100) if equity > 0 else Decimal(0)
        )

        sharpe = self._sharpe_ratio(equity_curve, equity)
        max_dd = self._max_drawdown(equity_curve)

        wins = [t["pnl"] for t in trades if t.get("is_win")]
        losses = [t["pnl"] for t in trades if not t.get("is_win") and "pnl" in t]
        total_trades = len(trades)
        win_rate = (
            Decimal(str(len(wins))) / Decimal(str(total_trades))
            if total_trades > 0 else Decimal(0)
        )
        avg_win = sum(wins) / Decimal(str(len(wins))) if wins else Decimal(0)
        avg_loss = abs(sum(losses)) / Decimal(str(len(losses))) if losses else Decimal(1)
        avg_wl = avg_win / avg_loss if avg_loss > 0 else Decimal(0)

        monthly = self._monthly_returns(equity_curve, equity)

        return BacktestResult(
            strategy_name=strategy.__class__.__name__,
            symbols=symbols,
            start_time=start_time,
            end_time=end_time,
            initial_equity=equity,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd,
            win_rate=win_rate,
            total_trades=total_trades,
            avg_win_loss_ratio=avg_wl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            monthly_returns=monthly,
            equity_curve=equity_curve,
            trades=trades,
        )

    def _slippage(self, symbol: str) -> Decimal:
        """Return the per-symbol slippage multiplier."""
        return self.config.slippages.get(symbol, self.config.slippages.get("default", Decimal(0)))

    def _portfolio_value(
        self,
        portfolio: PortfolioAccount,
        positions: dict[str, Position],
        data: dict[str, pd.DataFrame],
        at_ts: datetime | None = None,
    ) -> Decimal:
        """Compute current portfolio total value.

        If at_ts is provided, positions are valued at the close price of that
        timestamp; otherwise iloc[-1] is used (useful for final-stats computation
        when ts is no longer in scope).
        """
        cash = portfolio.cash_balance
        pos_value = Decimal(0)
        for sym, pos in positions.items():
            if sym in data and not data[sym].empty:
                df = data[sym]
                if at_ts is not None:
                    # Value position at the close of bar matching at_ts
                    rows = df[df["timestamp"] == at_ts]
                    if not rows.empty:
                        last_close = Decimal(str(rows["close"].iloc[0]))
                    else:
                        last_close = Decimal(str(df["close"].iloc[-1]))
                else:
                    last_close = Decimal(str(df["close"].iloc[-1]))
                pos_value += pos.qty * last_close
        return cash + pos_value

    def _sharpe_ratio(
        self,
        equity_curve: list[tuple[datetime, Decimal]],
        initial: Decimal,
    ) -> float:
        """Compute annualised Sharpe ratio from equity curve."""
        if len(equity_curve) < 2:
            return 0.0

        returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev_val = float(equity_curve[i - 1][1])
            curr_val = float(equity_curve[i][1])
            if prev_val > 0:
                returns.append((curr_val - prev_val) / prev_val)

        if not returns:
            return 0.0

        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = variance**0.5

        annual_ret = mean_ret * self.BARS_PER_YEAR
        annual_std = std_ret * (self.BARS_PER_YEAR**0.5)

        return float(annual_ret / annual_std) if annual_std > 0 else 0.0

    def _max_drawdown(
        self,
        equity_curve: list[tuple[datetime, Decimal]],
    ) -> Decimal:
        """Compute maximum drawdown from equity curve."""
        if not equity_curve:
            return Decimal(0)

        peak = equity_curve[0][1]
        max_dd = Decimal(0)

        for _, val in equity_curve:
            if val > peak:
                peak = val
            drawdown = (peak - val) / peak if peak > 0 else Decimal(0)
            if drawdown > max_dd:
                max_dd = drawdown

        return max_dd * Decimal(100)  # as percentage

    def _monthly_returns(
        self,
        equity_curve: list[tuple[datetime, Decimal]],
        initial: Decimal,
    ) -> dict[str, Decimal]:
        """Group returns by calendar month."""
        if not equity_curve:
            return {}

        monthly: dict[str, list[float]] = {}
        for ts, val in equity_curve:
            key = ts.strftime("%Y-%m")
            monthly.setdefault(key, []).append(float(val))

        result: dict[str, Decimal] = {}
        prev_val: float | None = None
        for key in sorted(monthly.keys()):
            month_end = Decimal(str(monthly[key][-1]))
            if prev_val is not None and prev_val > 0:
                ret = (month_end - Decimal(str(prev_val))) / Decimal(str(prev_val)) * 100
                result[key] = ret
            prev_val = float(month_end)

        return result
