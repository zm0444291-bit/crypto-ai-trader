#!/usr/bin/env python3
"""
验证最优策略在真实项目回测引擎中的表现
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.backtest.engine import BacktestConfig, BacktestEngine
from trading.backtest.store import ParquetCandleStore


# 测试最优策略在真实引擎中的表现
STRATS_TO_TEST = [
    # BB策略（从扫描结果选出）
    ("BB(5,0.5)", "xauusd", "1d"),
    ("BB(5,1.0)", "xauusd", "1d"),
    ("BB(12,1.5)", "xauusd", "1d"),
    ("BB(14,1.0)", "xauusd", "1d"),
    ("BB(5,0.5)", "eurusd", "1d"),
    ("BB(5,0.5)", "gbpusd", "1d"),
    # RSI策略（对照组）
    ("RSI(5,30,85)", "xauusd", "1d"),
    ("RSI(7,25,75)", "xauusd", "1d"),
]

store = ParquetCandleStore(Path("backtest_data/candles"))


def load_df(symbol, interval, year):
    """Load parquet as DataFrame matching what the engine expects."""
    suffix = f"_{interval}"
    fpath = Path(f"backtest_data/candles/{symbol}{suffix}.parquet")
    if not fpath.exists():
        return None
    df = pd.read_parquet(fpath)
    # Standardize column names
    col_map = {}
    for c in df.columns:
        lc = c.lower().strip()
        if lc == 'timestamp' or lc == 'date' or lc == 'time':
            col_map[c] = 'timestamp'
        elif lc in ('open', 'high', 'low', 'close', 'volume'):
            col_map[c] = lc
    df = df.rename(columns=col_map)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    df = df.sort_values('timestamp').reset_index(drop=True)
    # Convert to float
    for c in ['open', 'high', 'low', 'close', 'volume']:
        if c in df.columns:
            df[c] = df[c].astype(float)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year, 12, 31, tzinfo=timezone.utc)
    return df[(df['timestamp'] >= start) & (df['timestamp'] <= end)].copy()


def run_bb_backtest(symbol, interval, period, std_mult, year):
    """Run BB strategy manually through the project engine."""
    df = load_df(symbol, interval, year)
    if df is None or len(df) < period + 1:
        return None

    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()

    signals = []
    for i in range(period, len(closes) - 1):
        win = closes[max(0, i - period):i]
        mu = sum(win) / len(win)
        sd = (sum((c - mu) ** 2 for c in win) / len(win)) ** 0.5
        lo = mu - std_mult * sd
        hi = mu + std_mult * sd
        if closes[i] <= lo:
            signals.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            signals.append(("sell", closes[i], i))

    # P&L with % returns
    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    wins, losses = 0, 0
    longs, shorts = 0, 0
    pos = None
    entry_price = 0.0

    for side, price, _ in signals:
        if side == "buy":
            if pos == "short":
                pct = (entry_price - price) / entry_price * 100
                equity *= (1 + pct / 100)
                wins += 1 if pct > 0 else 0
                losses += 1 if pct <= 0 else 0
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "long"
            longs += 1
        elif side == "sell":
            if pos == "long":
                pct = (price - entry_price) / entry_price * 100
                equity *= (1 + pct / 100)
                wins += 1 if pct > 0 else 0
                losses += 1 if pct <= 0 else 0
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "short"
            shorts += 1

    if pos is not None:
        last_price = closes[-1]
        pct = (last_price - entry_price) / entry_price * 100 if pos == "long" else (entry_price - last_price) / entry_price * 100
        equity *= (1 + pct / 100)
        wins += 1 if pct > 0 else 0
        losses += 1 if pct <= 0 else 0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)

    total_ret = (equity - 10_000) / 10_000 * 100
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
    sharpe = total_ret / (abs(max_dd) + 0.1)
    return {
        "ret": total_ret, "sharpe": sharpe, "max_dd": max_dd,
        "trades": len(signals), "win_rate": win_rate,
        "longs": longs, "shorts": shorts,
    }


def run_rsi_backtest(symbol, interval, period, os, ob, year):
    df = load_df(symbol, interval, year)
    if df is None or len(df) < period + 1:
        return None
    closes = df["close"].tolist()
    signals = []
    for i in range(period + 1, len(closes) - 1):
        deltas = [closes[j] - closes[j - 1] for j in range(i - period, i)]
        g = sum(d for d in deltas if d > 0) / period
        l = sum(-d for d in deltas if d < 0) / period
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            signals.append(("buy", closes[i], i))
        elif rsi > ob:
            signals.append(("sell", closes[i], i))

    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    wins, losses = 0, 0
    longs, shorts = 0, 0
    pos = None
    entry_price = 0.0

    for side, price, _ in signals:
        if side == "buy":
            if pos == "short":
                pct = (entry_price - price) / entry_price * 100
                equity *= (1 + pct / 100)
                wins += 1 if pct > 0 else 0
                losses += 1 if pct <= 0 else 0
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "long"
            longs += 1
        elif side == "sell":
            if pos == "long":
                pct = (price - entry_price) / entry_price * 100
                equity *= (1 + pct / 100)
                wins += 1 if pct > 0 else 0
                losses += 1 if pct <= 0 else 0
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "short"
            shorts += 1

    if pos is not None:
        last_price = closes[-1]
        pct = (last_price - entry_price) / entry_price * 100 if pos == "long" else (entry_price - last_price) / entry_price * 100
        equity *= (1 + pct / 100)
        wins += 1 if pct > 0 else 0
        losses += 1 if pct <= 0 else 0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)

    total_ret = (equity - 10_000) / 10_000 * 100
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
    sharpe = total_ret / (abs(max_dd) + 0.1)
    return {
        "ret": total_ret, "sharpe": sharpe, "max_dd": max_dd,
        "trades": len(signals), "win_rate": win_rate,
        "longs": longs, "shorts": shorts,
    }


print(f"{'Strategy':<22} {'Sym':<8} {'Yr':<5} {'Ret%':>8} {'Sharpe':>8} {'MaxDD%':>8} {'Trades':>7} {'Longs':>6} {'Shorts':>7}")
print("=" * 90)

all_results = []

# BB strategies
bb_strats = [
    ("BB(5,0.5)", 5, 0.5),
    ("BB(5,1.0)", 5, 1.0),
    ("BB(5,1.5)", 5, 1.5),
    ("BB(7,1.0)", 7, 1.0),
    ("BB(10,1.0)", 10, 1.0),
    ("BB(12,1.5)", 12, 1.5),
    ("BB(14,1.0)", 14, 1.0),
]

for name, period, std in bb_strats:
    for sym in ["xauusd", "eurusd", "gbpusd"]:
        for year in [2023, 2024, 2025]:
            r = run_bb_backtest(sym, "1d", period, std, year)
            if r and r["trades"] >= 5:
                all_results.append((name, sym, year, r))
                print(f"{name:<22} {sym:<8} {year:<5} {r['ret']:>+8.1f}% {r['sharpe']:>+8.2f} {r['max_dd']:>8.1f}% {r['trades']:>7} {r['longs']:>6} {r['shorts']:>7}")

print()
print("=" * 90)
print("RSI comparison:")
rsi_strats = [
    ("RSI(5,30,85)", 5, 30, 85),
    ("RSI(7,25,75)", 7, 25, 75),
    ("RSI(10,30,85)", 10, 30, 85),
]
for name, period, os, ob in rsi_strats:
    for sym in ["xauusd"]:
        for year in [2023, 2024, 2025]:
            r = run_rsi_backtest(sym, "1d", period, os, ob, year)
            if r and r["trades"] >= 5:
                print(f"{name:<22} {sym:<8} {year:<5} {r['ret']:>+8.1f}% {r['sharpe']:>+8.2f} {r['max_dd']:>8.1f}% {r['trades']:>7} {r['longs']:>6} {r['shorts']:>7}")
