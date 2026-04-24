"""
Backtest the CompositeTradingSystem on XAUUSD 1d (2023-2025).
Tests whether the adaptive multi-strategy system beats the single BB strategy.
"""
import pandas as pd
import numpy as np

from trading.strategies.active.composite_system import CompositeTradingSystem
from trading.strategies.active.regime_detector import detect_regime


def backtest_system(symbol: str, df: pd.DataFrame, system: CompositeTradingSystem) -> dict:
    """
    Backtest the composite system bar-by-bar.
    Returns performance metrics.
    """
    equity = 1.0
    position = 0
    entry_price = 0.0
    trades = []

    for i in range(2, len(df)):
        df_slice = df.iloc[: i + 1]
        signals = system.generate_signals(symbol, df_slice)

        if signals:
            close_now = float(df["close"].iloc[i])
            for sig in signals:
                if sig.side == "buy" and position == 0:
                    position = 1
                    entry_price = close_now
                    equity *= (1 - 0.0005)  # spread cost on entry

                elif sig.side == "sell" and position == 1:
                    ret = (close_now - entry_price) / entry_price
                    won = ret > 0
                    equity *= (1 + ret)
                    equity *= (1 - 0.0005)  # spread cost on exit
                    trades.append({"return": ret, "won": won})
                    system.record_outcome(won, ret)
                    position = 0
                    entry_price = 0.0

    # Close open position at end
    if position == 1:
        close_now = float(df["close"].iloc[-1])
        ret = (close_now - entry_price) / entry_price
        trades.append({"return": ret, "won": ret > 0})
        equity *= (1 + ret)
        position = 0

    if not trades:
        return {
            "total_return": 0.0,
            "ann_return": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_dd": 0.0,
            "equity": 1.0,
        }

    rets = [t["return"] for t in trades]
    wins = [t for t in rets if t > 0]
    losses = [t for t in rets if t <= 0]

    # Max drawdown on equity curve
    peak = 1.0
    max_dd = 0.0
    eq = 1.0
    for t in rets:
        eq *= 1 + t
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    n_years = len(df) / 252
    ann_return = (equity ** (1 / n_years)) - 1 if n_years > 0 else 0

    return {
        "total_return": (equity - 1.0) * 100,
        "ann_return": ann_return * 100,
        "n_trades": len(trades),
        "win_rate": len(wins) / len(rets) * 100,
        "avg_win": np.mean(wins) * 100 if wins else 0.0,
        "avg_loss": np.mean(losses) * 100 if losses else 0.0,
        "max_dd": max_dd * 100,
        "equity": equity,
        "returns": rets,
    }


def main() -> None:
    # Load data
    df = pd.read_parquet("backtest_data/candles/xauusd_1d.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.set_index("timestamp")
    print(f"Data: {len(df)} bars, {df.index[0].date()} -> {df.index[-1].date()}")
    print()

    # Per-year breakdown
    years = [2023, 2024, 2025]
    results = {}

    for year in years:
        mask = df.index.year == year
        df_year = df[mask]
        if len(df_year) < 50:
            continue

        system = CompositeTradingSystem(symbol="XAUUSD")
        r = backtest_system("XAUUSD", df_year, system)
        results[year] = r
        print(f"=== {year} ===")
        print(f"  Return:   {r['total_return']:+.1f}%")
        print(f"  Ann Ret:  {r['ann_return']:+.1f}%")
        print(f"  Trades:   {r['n_trades']}")
        print(f"  Win%:     {r['win_rate']:.1f}%")
        print(f"  Avg Win:  {r['avg_win']:+.2f}%  Avg Loss: {r['avg_loss']:+.2f}%")
        print(f"  MaxDD:    {r['max_dd']:.1f}%")
        regime = system.get_last_regime()
        print(f"  Final regime: {regime.state if regime else 'N/A'}")
        if r.get("returns"):
            print(f"  Returns:  {[f'{t*100:.2f}%' for t in r['returns']]}")
        print()

    # 3-year cumulative
    total_equity = 1.0
    for year, r in results.items():
        total_equity *= r["equity"]
    print(f"=== 3-Year Cumulative Return: {(total_equity - 1) * 100:+.1f}% ===")
    print(f"    Final equity factor: {total_equity:.4f}x")

    # Regime distribution
    print()
    print("=== Regime Distribution (full 3yr) ===")
    regime_counts = {"BULL_TREND": 0, "BEAR_TREND": 0, "RANGE_BOUND": 0, "VOLATILE_CHOP": 0}
    for i in range(100, len(df)):
        r = detect_regime(df["high"].iloc[: i + 1], df["low"].iloc[: i + 1], df["close"].iloc[: i + 1])
        regime_counts[r.state] += 1
    total = sum(regime_counts.values())
    for state, count in regime_counts.items():
        print(f"  {state}: {count} bars ({count / total * 100:.1f}%)")


if __name__ == "__main__":
    main()
