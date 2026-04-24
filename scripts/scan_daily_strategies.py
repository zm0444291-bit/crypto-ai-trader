#!/usr/bin/env python3
"""
日线双向策略系统性扫描 — 迭代式
Run 1: 扫描所有策略参数，输出最优候选
Run 2: 基于Run 1结果精细化调参
Run 3: 组合最优策略，验证3年+多品种
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import dataclass
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# ─── 数据加载 ───────────────────────────────────────────────────────────────

CANDLE_BASE = Path("backtest_data/candles")

INTERVALS = {
    "1d": ["xauusd", "eurusd", "gbpusd"],
    "1h": ["xauusd", "eurusd", "gbpusd", "btcusdt"],
    "15m": ["btcusdt"],
}

YEARS = {
    "1d": [2023, 2024, 2025],
    "1h": [2025],
    "15m": [2025],
}

_ohlc_cache: dict[str, pd.DataFrame] = {}

def load_ohlc(symbol: str, interval: str) -> pd.DataFrame | None:
    key = f"{symbol}_{interval}"
    if key in _ohlc_cache:
        return _ohlc_cache[key]
    fpath = CANDLE_BASE / f"{symbol}_{interval}.parquet"
    if not fpath.exists():
        return None
    df = pd.read_parquet(fpath)
    ts_col = "timestamp"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.sort_values(ts_col).reset_index(drop=True)
    _ohlc_cache[key] = df
    return df


# ─── 简单P&L回测（自包含，不依赖项目引擎） ────────────────────────────────

@dataclass
class BacktestResult:
    strat_name: str
    symbol: str
    interval: str
    year: int
    ret: float       # % return
    sharpe: float    # ret / max_dd (simplified)
    max_dd: float    # %
    trades: int
    win_rate: float
    longs: int
    shorts: int
    longs_win: int
    shorts_win: int


def backtest(symbol: str, interval: str, strat_fn, year: int) -> BacktestResult:
    """
    strat_fn(df: pd.DataFrame) -> list[tuple(side: str, idx: int)]
    side = 'buy' or 'sell'
    idx = index into df (the bar at which signal fires)
    """
    df = load_ohlc(symbol, interval)
    if df is None:
        return _empty_result(symbol, interval, year, strat_fn.__name__)

    df_yr = df[(df["timestamp"] >= datetime(year, 1, 1, tzinfo=timezone.utc)) &
               (df["timestamp"] <= datetime(year, 12, 31, tzinfo=timezone.utc))].copy()
    if df_yr.empty:
        return _empty_result(symbol, interval, year, strat_fn.__name__)
    # Convert Decimal cols to float
    for col in ["open","high","low","close","volume"]:
        if col in df_yr.columns:
            df_yr[col] = df_yr[col].astype(float)

    signals = strat_fn(df_yr)  # list of (side, price, idx)
    if not signals:
        return _empty_result(symbol, interval, year, strat_fn.__name__)

    equity = 10_000.0
    peak = equity
    max_dd = 0.0
    wins, losses = 0, 0
    longs_wins, shorts_wins = 0, 0
    pos = None  # None | 'long' | 'short'
    entry_price = 0.0

    for side, price, _ in signals:
        if side == "buy":
            if pos == "short":
                pct = (entry_price - price) / entry_price * 100
                equity *= (1 + pct / 100)
                if pct > 0:
                    wins += 1
                    shorts_wins += 1
                else:
                    losses += 1
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "long"
        elif side == "sell":
            if pos == "long":
                pct = (price - entry_price) / entry_price * 100
                equity *= (1 + pct / 100)
                if pct > 0:
                    wins += 1
                    longs_wins += 1
                else:
                    losses += 1
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "short"

    # close at end
    if pos is not None:
        last_price = df_yr["close"].iloc[-1]
        if pos == "long":
            pct = (last_price - entry_price) / entry_price * 100
        else:
            pct = (entry_price - last_price) / entry_price * 100
        equity *= (1 + pct / 100)
        if pct > 0:
            wins += 1
            if pos == "long":
                longs_wins += 1
            else:
                shorts_wins += 1
        else:
            losses += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)

    total_ret = (equity - 10_000) / 10_000 * 100
    sharpe = total_ret / (abs(max_dd) + 0.1)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0

    longs = sum(1 for s in signals if s[0] == "buy")
    shorts = sum(1 for s in signals if s[0] == "sell")

    return BacktestResult(
        strat_name=strat_fn.__name__,
        symbol=symbol,
        interval=interval,
        year=year,
        ret=total_ret,
        sharpe=sharpe,
        max_dd=max_dd,
        trades=len(signals),
        win_rate=win_rate,
        longs=longs,
        shorts=shorts,
        longs_win=longs_wins,
        shorts_win=shorts_wins,
    )


def _empty_result(symbol, interval, year, name):
    return BacktestResult(name, symbol, interval, year, 0, 0, 0, 0, 0, 0, 0, 0, 0)


# ─── 策略定义 ───────────────────────────────────────────────────────────────

def _ema(data: list[float], n: int) -> list[float]:
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    # pad with first value so output length == len(data)
    out = [data[0]] * (n - 1) + [e]
    for v in data[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _atr(highs, lows, closes, n: int) -> list[float]:
    trs = [max(highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    out = []
    for i in range(len(trs)):
        out.append(sum(trs[max(0, i - n + 1):i + 1]) / min(i + 1, n))
    return out


# ── RSI ──────────────────────────────────────────────────────────────────────

def RSI_5_20_80(df):
    closes = df["close"].tolist()
    n = 5
    os, ob = 20, 80
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_5_25_75(df):
    closes = df["close"].tolist()
    n = 5
    os, ob = 25, 75
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_5_30_70(df):
    closes = df["close"].tolist()
    n = 5
    os, ob = 30, 70
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_7_20_80(df):
    closes = df["close"].tolist()
    n = 7
    os, ob = 20, 80
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_7_25_75(df):
    closes = df["close"].tolist()
    n = 7
    os, ob = 25, 75
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_7_30_70(df):
    closes = df["close"].tolist()
    n = 7
    os, ob = 30, 70
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_10_20_80(df):
    closes = df["close"].tolist()
    n = 10
    os, ob = 20, 80
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_10_25_75(df):
    closes = df["close"].tolist()
    n = 10
    os, ob = 25, 75
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_10_30_70(df):
    closes = df["close"].tolist()
    n = 10
    os, ob = 30, 70
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_14_20_80(df):
    closes = df["close"].tolist()
    n = 14
    os, ob = 20, 80
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_14_25_75(df):
    closes = df["close"].tolist()
    n = 14
    os, ob = 25, 75
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_14_30_70(df):
    closes = df["close"].tolist()
    n = 14
    os, ob = 30, 70
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_21_20_80(df):
    closes = df["close"].tolist()
    n = 21
    os, ob = 20, 80
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

def RSI_21_30_70(df):
    closes = df["close"].tolist()
    n = 21
    os, ob = 30, 70
    sigs = []
    for i in range(n + 1, len(closes)):
        deltas = [closes[j] - closes[j - 1] for j in range(i - n, i)]
        g = sum(d for d in deltas if d > 0) / n
        l = sum(-d for d in deltas if d < 0) / n
        rs = g / l if l > 0 else 999
        rsi = 100 - (100 / (1 + rs))
        if rsi < os:
            sigs.append(("buy", closes[i], i))
        elif rsi > ob:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── MACD ─────────────────────────────────────────────────────────────────────

def MACD_5_13_4(df):
    closes = df["close"].tolist()
    f, s, sig = 5, 13, 4
    ef = _ema(closes, f)
    es = _ema(closes, s)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig_line = _ema(macd, sig)
    sigs = []
    for i in range(s + sig, len(closes) - 1):
        if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
            sigs.append(("buy", closes[i], i))
        elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
            sigs.append(("sell", closes[i], i))
    return sigs

def MACD_8_21_9(df):
    closes = df["close"].tolist()
    f, s, sig = 8, 21, 9
    ef = _ema(closes, f)
    es = _ema(closes, s)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig_line = _ema(macd, sig)
    sigs = []
    for i in range(s + sig, len(closes) - 1):
        if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
            sigs.append(("buy", closes[i], i))
        elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
            sigs.append(("sell", closes[i], i))
    return sigs

def MACD_12_26_9(df):
    closes = df["close"].tolist()
    f, s, sig = 12, 26, 9
    ef = _ema(closes, f)
    es = _ema(closes, s)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig_line = _ema(macd, sig)
    sigs = []
    for i in range(s + sig, len(closes) - 1):
        if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
            sigs.append(("buy", closes[i], i))
        elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
            sigs.append(("sell", closes[i], i))
    return sigs

def MACD_3_10_4(df):
    closes = df["close"].tolist()
    f, s, sig = 3, 10, 4
    ef = _ema(closes, f)
    es = _ema(closes, s)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig_line = _ema(macd, sig)
    sigs = []
    for i in range(s + sig, len(closes) - 1):
        if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
            sigs.append(("buy", closes[i], i))
        elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
            sigs.append(("sell", closes[i], i))
    return sigs

def MACD_6_19_6(df):
    closes = df["close"].tolist()
    f, s, sig = 6, 19, 6
    ef = _ema(closes, f)
    es = _ema(closes, s)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    sig_line = _ema(macd, sig)
    sigs = []
    for i in range(s + sig, len(closes) - 1):
        if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
            sigs.append(("buy", closes[i], i))
        elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── Bollinger Bands ───────────────────────────────────────────────────────────

def BB_10_2(df):
    closes = df["close"].tolist()
    p, m = 10, 2.0
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

def BB_14_2(df):
    closes = df["close"].tolist()
    p, m = 14, 2.0
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

def BB_20_2(df):
    closes = df["close"].tolist()
    p, m = 20, 2.0
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

def BB_20_15(df):
    closes = df["close"].tolist()
    p, m = 20, 1.5
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

def BB_20_25(df):
    closes = df["close"].tolist()
    p, m = 20, 2.5
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

def BB_30_2(df):
    closes = df["close"].tolist()
    p, m = 30, 2.0
    sigs = []
    for i in range(p + 1, len(closes)):
        win = closes[i - p:i]
        mu = sum(win) / p
        sd = (sum((c - mu) ** 2 for c in win) / p) ** 0.5
        lo, hi = mu - m * sd, mu + m * sd
        if closes[i] <= lo:
            sigs.append(("buy", closes[i], i))
        elif closes[i] >= hi:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── ATR Breakout ──────────────────────────────────────────────────────────────

def ATRBrk_5_05(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    p, m = 5, 0.5
    atr = _atr(highs, lows, closes, p)
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        if closes[i] > closes[i - 1] + atr[i] * m:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < closes[i - 1] - atr[i] * m:
            sigs.append(("sell", closes[i], i))
    return sigs

def ATRBrk_10_1(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    p, m = 10, 1.0
    atr = _atr(highs, lows, closes, p)
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        if closes[i] > closes[i - 1] + atr[i] * m:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < closes[i - 1] - atr[i] * m:
            sigs.append(("sell", closes[i], i))
    return sigs

def ATRBrk_14_2(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    p, m = 14, 2.0
    atr = _atr(highs, lows, closes, p)
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        if closes[i] > closes[i - 1] + atr[i] * m:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < closes[i - 1] - atr[i] * m:
            sigs.append(("sell", closes[i], i))
    return sigs

def ATRBrk_14_15(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    p, m = 14, 1.5
    atr = _atr(highs, lows, closes, p)
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        if closes[i] > closes[i - 1] + atr[i] * m:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < closes[i - 1] - atr[i] * m:
            sigs.append(("sell", closes[i], i))
    return sigs

def ATRBrk_21_2(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    p, m = 21, 2.0
    atr = _atr(highs, lows, closes, p)
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        if closes[i] > closes[i - 1] + atr[i] * m:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < closes[i - 1] - atr[i] * m:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── Donchian ─────────────────────────────────────────────────────────────────

def Donchian_10(df):
    closes = df["close"].tolist()
    p = 10
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        look = closes[max(0, i - p):i]
        if closes[i] > max(look):
            sigs.append(("buy", closes[i], i))
        elif closes[i] < min(look):
            sigs.append(("sell", closes[i], i))
    return sigs

def Donchian_20(df):
    closes = df["close"].tolist()
    p = 20
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        look = closes[max(0, i - p):i]
        if closes[i] > max(look):
            sigs.append(("buy", closes[i], i))
        elif closes[i] < min(look):
            sigs.append(("sell", closes[i], i))
    return sigs

def Donchian_30(df):
    closes = df["close"].tolist()
    p = 30
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        look = closes[max(0, i - p):i]
        if closes[i] > max(look):
            sigs.append(("buy", closes[i], i))
        elif closes[i] < min(look):
            sigs.append(("sell", closes[i], i))
    return sigs

def Donchian_50(df):
    closes = df["close"].tolist()
    p = 50
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        look = closes[max(0, i - p):i]
        if closes[i] > max(look):
            sigs.append(("buy", closes[i], i))
        elif closes[i] < min(look):
            sigs.append(("sell", closes[i], i))
    return sigs

# ── EMA Cross ─────────────────────────────────────────────────────────────────

def EMACross_5_20(df):
    closes = df["close"].tolist()
    f, s = 5, 20
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

def EMACross_5_40(df):
    closes = df["close"].tolist()
    f, s = 5, 40
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

def EMACross_10_30(df):
    closes = df["close"].tolist()
    f, s = 10, 30
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

def EMACross_10_50(df):
    closes = df["close"].tolist()
    f, s = 10, 50
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

def EMACross_20_60(df):
    closes = df["close"].tolist()
    f, s = 20, 60
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

def EMACross_8_21(df):
    closes = df["close"].tolist()
    f, s = 8, 21
    ef = _ema(closes, f)
    es = _ema(closes, s)
    sigs = []
    for i in range(s, len(closes) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            sigs.append(("buy", closes[i], i))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── Keltner ───────────────────────────────────────────────────────────────────

def Keltner_20_14_2(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    ep, ap, m = 20, 14, 2.0
    mid = _ema(closes, ep)
    atr_vals = _atr(highs, lows, closes, ap)
    sigs = []
    for i in range(max(ep, ap) + 1, len(closes) - 1):
        hi = mid[i] + atr_vals[i] * m
        lo = mid[i] - atr_vals[i] * m
        if closes[i] > hi:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < lo:
            sigs.append(("sell", closes[i], i))
    return sigs

def Keltner_10_10_15(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    ep, ap, m = 10, 10, 1.5
    mid = _ema(closes, ep)
    atr_vals = _atr(highs, lows, closes, ap)
    sigs = []
    for i in range(max(ep, ap) + 1, len(closes) - 1):
        hi = mid[i] + atr_vals[i] * m
        lo = mid[i] - atr_vals[i] * m
        if closes[i] > hi:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < lo:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── Stochastic ────────────────────────────────────────────────────────────────

def Stoch_5_3_20_80(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    k, d, os, ob = 5, 3, 20, 80
    k_vals = []
    for i in range(k, len(closes)):
        lo = min(lows[max(0, i - k):i])
        hi = max(highs[max(0, i - k):i])
        r = hi - lo
        k_vals.append(((closes[i] - lo) / r * 100) if r > 0 else 50)
    sigs = []
    for i in range(k + d - 1, len(k_vals) - 1):
        d_val = sum(k_vals[i - d + 1:i + 1]) / d
        prev_d = sum(k_vals[i - d:i]) / d
        if k_vals[i] > os and prev_d <= os and d_val > os:
            sigs.append(("buy", closes[i + k], i + k))
        elif k_vals[i] < ob and prev_d >= ob and d_val < ob:
            sigs.append(("sell", closes[i + k], i + k))
    return sigs

def Stoch_9_3_20_80(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    k, d, os, ob = 9, 3, 20, 80
    k_vals = []
    for i in range(k, len(closes)):
        lo = min(lows[max(0, i - k):i])
        hi = max(highs[max(0, i - k):i])
        r = hi - lo
        k_vals.append(((closes[i] - lo) / r * 100) if r > 0 else 50)
    sigs = []
    for i in range(k + d - 1, len(k_vals) - 1):
        d_val = sum(k_vals[i - d + 1:i + 1]) / d
        prev_d = sum(k_vals[i - d:i]) / d
        if k_vals[i] > os and prev_d <= os and d_val > os:
            sigs.append(("buy", closes[i + k], i + k))
        elif k_vals[i] < ob and prev_d >= ob and d_val < ob:
            sigs.append(("sell", closes[i + k], i + k))
    return sigs

def Stoch_14_3_20_80(df):
    closes = df["close"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()
    k, d, os, ob = 14, 3, 20, 80
    k_vals = []
    for i in range(k, len(closes)):
        lo = min(lows[max(0, i - k):i])
        hi = max(highs[max(0, i - k):i])
        r = hi - lo
        k_vals.append(((closes[i] - lo) / r * 100) if r > 0 else 50)
    sigs = []
    for i in range(k + d - 1, len(k_vals) - 1):
        d_val = sum(k_vals[i - d + 1:i + 1]) / d
        prev_d = sum(k_vals[i - d:i]) / d
        if k_vals[i] > os and prev_d <= os and d_val > os:
            sigs.append(("buy", closes[i + k], i + k))
        elif k_vals[i] < ob and prev_d >= ob and d_val < ob:
            sigs.append(("sell", closes[i + k], i + k))
    return sigs

# ── SMA Trend ─────────────────────────────────────────────────────────────────

def SMA_20(df):
    closes = df["close"].tolist()
    p = 20
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        sma = sum(closes[i - p:i]) / p
        if closes[i] > sma and closes[i - 1] <= sma:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < sma and closes[i - 1] >= sma:
            sigs.append(("sell", closes[i], i))
    return sigs

def SMA_50(df):
    closes = df["close"].tolist()
    p = 50
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        sma = sum(closes[i - p:i]) / p
        if closes[i] > sma and closes[i - 1] <= sma:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < sma and closes[i - 1] >= sma:
            sigs.append(("sell", closes[i], i))
    return sigs

def SMA_100(df):
    closes = df["close"].tolist()
    p = 100
    sigs = []
    for i in range(p + 1, len(closes) - 1):
        sma = sum(closes[i - p:i]) / p
        if closes[i] > sma and closes[i - 1] <= sma:
            sigs.append(("buy", closes[i], i))
        elif closes[i] < sma and closes[i - 1] >= sma:
            sigs.append(("sell", closes[i], i))
    return sigs

# ── All strategies list ───────────────────────────────────────────────────────

ALL_STRATS = [
    # RSI
    RSI_5_20_80, RSI_5_25_75, RSI_5_30_70,
    RSI_7_20_80, RSI_7_25_75, RSI_7_30_70,
    RSI_10_20_80, RSI_10_25_75, RSI_10_30_70,
    RSI_14_20_80, RSI_14_25_75, RSI_14_30_70,
    RSI_21_20_80, RSI_21_30_70,
    # MACD
    MACD_5_13_4, MACD_8_21_9, MACD_12_26_9, MACD_3_10_4, MACD_6_19_6,
    # Bollinger Bands
    BB_10_2, BB_14_2, BB_20_2, BB_20_15, BB_20_25, BB_30_2,
    # ATR Breakout
    ATRBrk_5_05, ATRBrk_10_1, ATRBrk_14_15, ATRBrk_14_2, ATRBrk_21_2,
    # Donchian
    Donchian_10, Donchian_20, Donchian_30, Donchian_50,
    # EMA Cross
    EMACross_5_20, EMACross_5_40, EMACross_10_30, EMACross_10_50, EMACross_20_60, EMACross_8_21,
    # Keltner
    Keltner_20_14_2, Keltner_10_10_15,
    # Stochastic
    Stoch_5_3_20_80, Stoch_9_3_20_80, Stoch_14_3_20_80,
    # SMA
    SMA_20, SMA_50, SMA_100,
]


# ─── 主扫描 ───────────────────────────────────────────────────────────────

def scan():
    all_results: list[BacktestResult] = []

    total_combos = len(ALL_STRATS) * sum(len(v) for v in INTERVALS.values()) * sum(len(YEARS[v]) for v in YEARS)
    print(f"Total combos: {len(ALL_STRATS)} strats × {sum(len(v) for v in INTERVALS.values())} symbols × {sum(len(YEARS[v]) for v in YEARS)} years = {total_combos}")
    print()

    combo_num = 0
    for strat_fn in ALL_STRATS:
        strat_name = strat_fn.__name__
        for interval, symbols in INTERVALS.items():
            years = YEARS[interval]
            for sym in symbols:
                for year in years:
                    combo_num += 1
                    r = backtest(sym, interval, strat_fn, year)
                    if r.trades >= 5:  # 至少5笔交易
                        all_results.append(r)

        print(f"[{combo_num}/{total_combos}] {strat_name}: done", flush=True)

    # ── 汇总 ────────────────────────────────────────────────────────────────
    print(f"\n\n{'='*130}")
    print(f"{'Strategy':<22} {'Sym':<8} {'Int':<5} {'Yr':<5} {'Ret%':>8} {'Sharpe':>8} {'MaxDD%':>8} {'Trades':>7} {'Win%':>6} {'Longs':>6} {'Shorts':>7}")
    print(f"{'='*130}")

    # 按3年累计收益排序
    summary: dict[tuple, dict] = {}
    for r in all_results:
        key = (r.strat_name, r.symbol, r.interval)
        if key not in summary:
            summary[key] = {"results": [], "total_ret": 0.0, "prof_years": 0}
        summary[key]["results"].append(r)
        summary[key]["total_ret"] += r.ret
        for yr in summary[key]["results"]:
            if yr.ret > 0:
                summary[key]["prof_years"] += 1

    ranked = sorted(summary.items(), key=lambda x: x[1]["total_ret"], reverse=True)

    for (sname, sym, intr), data in ranked[:50]:
        res_list = data["results"]
        total_ret = data["total_ret"]
        avg_sharpe = sum(r.sharpe for r in res_list) / len(res_list)
        max_dd = max(r.max_dd for r in res_list)
        total_trades = sum(r.trades for r in res_list)
        avg_trades = total_trades / len(res_list)
        total_wins = sum(int(r.win_rate * r.trades) for r in res_list)
        avg_win = total_wins / total_trades if total_trades > 0 else 0
        years_str = ",".join(str(r.year) for r in res_list)
        longs = sum(r.longs for r in res_list)
        shorts = sum(r.shorts for r in res_list)
        print(f"{sname:<22} {sym:<8} {intr:<5} {years_str:<5} {total_ret:>+8.1f}% {avg_sharpe:>+8.2f} {max_dd:>8.1f}% {avg_trades:>7.0f} {avg_win:>6.0%} {longs:>6} {shorts:>7}")

    print(f"\nTotal results: {len(all_results)} | Strategy-symbol combos: {len(summary)}")
    return all_results


if __name__ == "__main__":
    scan()
