#!/usr/bin/env python3
"""
Round 2: 精细化参数扫描
- 扩展BB周期和std范围
- 扩展RSI参数范围
- 扩展Stochastic参数
- 扩展MACD参数
- ATR/Donchian更密集网格
- 所有1d品种（XAUUSD, EURUSD, GBPUSD）
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from dataclasses import dataclass
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

CANDLE_BASE = Path("backtest_data/candles")
INTERVALS = {"1d": ["xauusd", "eurusd", "gbpusd"]}
YEARS = {"1d": [2023, 2024, 2025]}

_ohlc_cache = {}

def load_ohlc(symbol: str, interval: str) -> pd.DataFrame | None:
    key = f"{symbol}_{interval}"
    if key in _ohlc_cache:
        return _ohlc_cache[key]
    fpath = CANDLE_BASE / f"{symbol}_{interval}.parquet"
    if not fpath.exists():
        return None
    df = pd.read_parquet(fpath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    _ohlc_cache[key] = df
    return df


def _ema(data: list[float], n: int) -> list[float]:
    if n <= 1:
        return data[:]
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    out = [data[0]] * (n - 1) + [e]
    for v in data[n:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def _atr(highs, lows, closes, n: int) -> list[float]:
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])) for i in range(1, len(closes))]
    out = []
    for i in range(len(trs)):
        out.append(sum(trs[max(0, i - n + 1):i + 1]) / min(i + 1, n))
    return out


# ─── 策略工厂 ───────────────────────────────────────────────────────────────

def make_rsi(period, os, ob):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        n = period
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
    strat.__name__ = f"RSI({period},{os},{ob})"
    return strat


def make_bb(period, std_mult):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        sigs = []
        for i in range(period + 1, len(closes)):
            win = closes[i - period:i]
            mu = sum(win) / len(win)
            sd = (sum((c - mu) ** 2 for c in win) / len(win)) ** 0.5
            lo = mu - std_mult * sd
            hi = mu + std_mult * sd
            if closes[i] <= lo:
                sigs.append(("buy", closes[i], i))
            elif closes[i] >= hi:
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"BB({period},{std_mult})"
    return strat


def make_macd(fast, slow, signal):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        if len(closes) < slow + signal + 2:
            return []
        ef = _ema(closes, fast)
        es = _ema(closes, slow)
        macd = [ef[i] - es[i] for i in range(len(closes))]
        sig_line = _ema(macd, signal)
        sigs = []
        for i in range(slow + signal, len(closes) - 1):
            if macd[i - 1] < sig_line[i - 1] and macd[i] > sig_line[i]:
                sigs.append(("buy", closes[i], i))
            elif macd[i - 1] > sig_line[i - 1] and macd[i] < sig_line[i]:
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"MACD({fast},{slow},{signal})"
    return strat


def make_stoch(k, d, os, ob):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        highs = df["high"].astype(float).tolist()
        lows = df["low"].astype(float).tolist()
        if len(closes) < k + d + 2:
            return []
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
            if k_vals[i] > os and prev_d <= os:
                sigs.append(("buy", closes[i + k], i + k))
            elif k_vals[i] < ob and prev_d >= ob:
                sigs.append(("sell", closes[i + k], i + k))
        return sigs
    strat.__name__ = f"Stoch({k},{d},{os},{ob})"
    return strat


def make_atr(period, mult):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        highs = df["high"].astype(float).tolist()
        lows = df["low"].astype(float).tolist()
        if len(closes) < period + 2:
            return []
        atr = _atr(highs, lows, closes, period)
        sigs = []
        for i in range(period, len(atr) - 1):
            if closes[i] > closes[i - 1] + atr[i] * mult:
                sigs.append(("buy", closes[i], i))
            elif closes[i] < closes[i - 1] - atr[i] * mult:
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"ATR({period},{mult})"
    return strat


def make_donchian(period):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        sigs = []
        for i in range(period + 1, len(closes) - 1):
            look = closes[max(0, i - period):i]
            if closes[i] > max(look):
                sigs.append(("buy", closes[i], i))
            elif closes[i] < min(look):
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"Donchian({period})"
    return strat


def make_emacross(fast, slow):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        if len(closes) < slow + 2:
            return []
        ef = _ema(closes, fast)
        es = _ema(closes, slow)
        sigs = []
        for i in range(slow, len(closes) - 1):
            if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
                sigs.append(("buy", closes[i], i))
            elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"EMACross({fast},{slow})"
    return strat


def make_keltner(ema_p, atr_p, mult):
    def strat(df):
        closes = df["close"].astype(float).tolist()
        highs = df["high"].astype(float).tolist()
        lows = df["low"].astype(float).tolist()
        if len(closes) < max(ema_p, atr_p) + 2:
            return []
        mid = _ema(closes, ema_p)
        atr_vals = _atr(highs, lows, closes, atr_p)
        sigs = []
        start = max(ema_p, atr_p)
        for i in range(start, len(closes) - 1):
            hi = mid[i] + atr_vals[i] * mult
            lo = mid[i] - atr_vals[i] * mult
            if closes[i] > hi:
                sigs.append(("buy", closes[i], i))
            elif closes[i] < lo:
                sigs.append(("sell", closes[i], i))
        return sigs
    strat.__name__ = f"Keltner({ema_p},{atr_p},{mult})"
    return strat


# ─── 回测 ─────────────────────────────────────────────────────────────────

@dataclass
class Result:
    name: str
    symbol: str
    year: int
    ret: float
    sharpe: float
    max_dd: float
    trades: int
    win_rate: float
    longs: int
    shorts: int


def backtest(symbol: str, strat_fn, year: int) -> Result:
    df = load_ohlc(symbol, "1d")
    if df is None:
        return Result(strat_fn.__name__, symbol, year, 0, 0, 0, 0, 0, 0, 0)
    df_yr = df[(df["timestamp"] >= datetime(year, 1, 1, tzinfo=timezone.utc)) &
                (df["timestamp"] <= datetime(year, 12, 31, tzinfo=timezone.utc))].copy()
    if df_yr.empty:
        return Result(strat_fn.__name__, symbol, year, 0, 0, 0, 0, 0, 0, 0)
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df_yr.columns:
            df_yr[c] = df_yr[c].astype(float)
    signals = strat_fn(df_yr)
    if not signals:
        return Result(strat_fn.__name__, symbol, year, 0, 0, 0, 0, 0, 0, 0)
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
                if pct > 0: wins += 1
                else: losses += 1
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "long"
            longs += 1
        elif side == "sell":
            if pos == "long":
                pct = (price - entry_price) / entry_price * 100
                equity *= (1 + pct / 100)
                if pct > 0: wins += 1
                else: losses += 1
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100)
            entry_price = price
            pos = "short"
            shorts += 1
    if pos is not None:
        last_price = df_yr["close"].iloc[-1]
        pct = (last_price - entry_price) / entry_price * 100 if pos == "long" else (entry_price - last_price) / entry_price * 100
        equity *= (1 + pct / 100)
        if pct > 0: wins += 1
        else: losses += 1
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100)
    total_ret = (equity - 10_000) / 10_000 * 100
    sharpe = total_ret / (abs(max_dd) + 0.1)
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else 0
    return Result(strat_fn.__name__, symbol, year, total_ret, sharpe, max_dd,
                  len(signals), win_rate, longs, shorts)


# ─── 参数网格（精细化） ─────────────────────────────────────────────────────

def build_strats():
    strats = []

    # RSI: period 3-21, oversold 15-40, overbought 60-85
    for n in [3, 5, 7, 9, 10, 12, 14, 21]:
        for os in [15, 20, 25, 30, 35]:
            for ob in [65, 70, 75, 80, 85]:
                if os >= ob: continue
                strats.append(make_rsi(n, os, ob))

    # BB: period 5-30, std 0.5-3.5
    for p in [5, 7, 10, 12, 14, 16, 18, 20, 25, 30]:
        for m in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]:
            strats.append(make_bb(p, m))

    # MACD: more combos
    for f, s, sig in [(3,8,3), (3,10,4), (5,13,4), (5,20,5), (6,19,6), (7,15,5), (8,21,9), (10,25,7), (12,26,9), (5,35,7)]:
        if f >= s: continue
        strats.append(make_macd(f, s, sig))

    # Stochastic
    for k in [3, 5, 7, 9, 14]:
        for d in [3, 5]:
            for os in [15, 20, 25, 30]:
                for ob in [70, 75, 80, 85]:
                    if os >= ob: continue
                    strats.append(make_stoch(k, d, os, ob))

    # ATR Breakout
    for p in [3, 5, 7, 10, 14, 21]:
        for m in [0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0]:
            strats.append(make_atr(p, m))

    # Donchian
    for p in [5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]:
        strats.append(make_donchian(p))

    # EMA Cross
    for f, s in [(3,8), (3,15), (5,10), (5,20), (5,40), (8,21), (10,20), (10,30), (10,50), (12,26), (20,50), (20,100)]:
        if f >= s: continue
        strats.append(make_emacross(f, s))

    # Keltner
    for ep in [5, 10, 15, 20]:
        for ap in [5, 10, 14, 20]:
            for m in [1.0, 1.5, 2.0, 2.5, 3.0]:
                strats.append(make_keltner(ep, ap, m))

    return strats


# ─── 主扫描 ───────────────────────────────────────────────────────────────

def scan():
    strats = build_strats()
    print(f"Total strategies to test: {len(strats)}")

    all_results = []
    for idx, strat_fn in enumerate(strats):
        for sym in ["xauusd", "eurusd", "gbpusd"]:
            for year in [2023, 2024, 2025]:
                r = backtest(sym, strat_fn, year)
                if r.trades >= 5 and r.ret > 0:
                    all_results.append(r)
        if (idx + 1) % 100 == 0:
            print(f"  [{idx+1}/{len(strats)}] done", flush=True)

    # 汇总
    summary = {}
    for r in all_results:
        key = (r.name, r.symbol)
        if key not in summary:
            summary[key] = []
        summary[key].append(r)

    # 过滤：3年都盈利 + 平均每年20+笔交易
    qualified = []
    for (name, sym), res_list in summary.items():
        if len(res_list) < 3:
            continue
        ret_by_yr = {r.year: r.ret for r in res_list}
        if any(v <= 0 for v in ret_by_yr.values()):
            continue
        avg_trades = sum(r.trades for r in res_list) / 3
        if avg_trades < 20:
            continue
        total_ret = sum(r.ret for r in res_list)
        max_dd = max(r.max_dd for r in res_list)
        total_wins = sum(int(r.win_rate * r.trades) for r in res_list)
        total_all = sum(r.trades for r in res_list)
        avg_win = total_wins / total_all if total_all > 0 else 0
        avg_sharpe = sum(r.sharpe for r in res_list) / 3
        qualified.append({
            "name": name, "sym": sym,
            "ret_2023": ret_by_yr.get(2023, 0),
            "ret_2024": ret_by_yr.get(2024, 0),
            "ret_2025": ret_by_yr.get(2025, 0),
            "total_ret": total_ret,
            "avg_sharpe": avg_sharpe,
            "max_dd": max_dd,
            "avg_trades": avg_trades,
            "win_rate": avg_win,
        })

    qualified.sort(key=lambda x: x["total_ret"], reverse=True)

    print(f"\n{'='*110}")
    print(f"{'Strategy':<28} {'Sym':<8} {'2023':>7} {'2024':>7} {'2025':>7} {'3yr':>7} {'Sharpe':>7} {'MaxDD':>7} {'Trd/yr':>7} {'Win%':>6}")
    print(f"{'='*110}")
    for q in qualified[:40]:
        print(f"{q['name']:<28} {q['sym']:<8} {q['ret_2023']:>+7.1f}% {q['ret_2024']:>+7.1f}% {q['ret_2025']:>+7.1f}% {q['total_ret']:>+7.1f}% {q['avg_sharpe']:>+7.2f} {q['max_dd']:>7.1f}% {q['avg_trades']:>7.0f} {q['win_rate']:>6.0%}")
    print(f"\nTotal: {len(qualified)} qualifying combos")
    return qualified


if __name__ == "__main__":
    scan()
