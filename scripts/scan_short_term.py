#!/usr/bin/env python3
"""scan_short_term.py — vectorized grid search for ShortTermSystem.

Key optimization: pure-numpy backtest loop (2ms/combo vs 330ms with pandas).
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
BB_PERIODS    = [5, 8, 10, 12]
BB_STDS       = [1.0, 1.5, 2.0]
EMA_FASTS    = [15]
EMA_SLOWS    = [50]
SL_ATRS      = [1.0, 1.3, 1.5, 1.7, 2.0, 2.3, 2.5]
TP_ATRS      = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
MAX_BARS_LIST = [3, 4, 5, 6]

# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class ScanResult:
    bb_period: int
    bb_std: float
    ema_fast: int
    ema_slow: int
    sl_atr: float
    tp_atr: float
    max_bars: int
    total_return: float
    num_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_dd: float
    expectancy: float
    score: float


# ---------------------------------------------------------------------------
# Rolling utilities
# ---------------------------------------------------------------------------
def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    out = np.empty(n, dtype=np.float64)
    cs = np.cumsum(arr)
    out[:window] = np.nan
    out[window:] = (cs[window:] - cs[:-window]) / window
    return out


def _rolling_var(close: np.ndarray, period: int) -> np.ndarray:
    """Rolling variance using Var(X) = E[X^2] - E[X]^2 — O(n) per combo."""
    mean    = _rolling_mean(close, period)
    mean_sq = _rolling_mean(close * close, period)
    var     = mean_sq - mean * mean
    var[:period - 1] = np.nan
    return var


# ---------------------------------------------------------------------------
# Pre-compute base arrays (shared across all combos)
# ---------------------------------------------------------------------------
def precompute_base(df: pd.DataFrame) -> dict:
    """Return dict of numpy arrays: close, high, low, atr, rsi, session_ok."""
    c  = df["close"].astype(np.float64).values
    h  = df["high"].astype(np.float64).values
    lo_ = df["low"].astype(np.float64).values
    n   = len(df)

    # ATR(14)
    pc  = np.empty(n, dtype=np.float64)
    pc[0] = c[0]
    pc[1:] = c[:-1]
    tr1 = h - lo_
    tr2 = np.abs(h - pc)
    tr3 = np.abs(lo_ - pc)
    tr  = np.maximum(np.maximum(tr1, tr2), tr3)
    atr = _rolling_mean(tr, 14)

    # RSI(14)
    d    = np.diff(c, prepend=c[0])
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    avg_g = _rolling_mean(gain, 14)
    avg_l = _rolling_mean(loss, 14)
    rsi   = 100.0 - 100.0 / (1.0 + avg_g / (avg_l + 1e-12))

    # Session mask: block 11-14 UTC
    ts    = pd.to_datetime(df["timestamp"])
    hours = np.array([t.hour for t in ts], dtype=np.int32)
    session_ok = ~((hours >= 11) & (hours < 15))

    return {
        "close": c, "high": h, "low": lo_,
        "atr": atr, "rsi": rsi,
        "session_ok": session_ok,
        "n": n,
    }


# ---------------------------------------------------------------------------
# BB cache: (6, 6, n) — indexed by period-index × std-index
# ---------------------------------------------------------------------------
def build_bb_cache(n: int, close: np.ndarray) -> np.ndarray:
    cache = np.empty((len(BB_PERIODS), len(BB_STDS), n), dtype=np.float64)
    for pi, bp in enumerate(BB_PERIODS):
        mid = _rolling_mean(close, bp)
        std = np.sqrt(_rolling_var(close, bp))
        for si, bs in enumerate(BB_STDS):
            cache[pi, si] = mid - std * bs
    return cache


# ---------------------------------------------------------------------------
# EMA cache: (4, 5, n) each for fast/slow
# ---------------------------------------------------------------------------
def build_ema_cache(n: int, close: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ef_cache = np.empty((len(EMA_FASTS), len(EMA_SLOWS), n), dtype=np.float64)
    es_cache = np.empty((len(EMA_FASTS), len(EMA_SLOWS), n), dtype=np.float64)
    alpha_f = np.array([2.0 / (f + 1) for f in EMA_FASTS])
    alpha_s = np.array([2.0 / (s + 1) for s in EMA_SLOWS])

    for efi, _ef in enumerate(EMA_FASTS):
        af = alpha_f[efi]
        for esi, _es in enumerate(EMA_SLOWS):
            as_ = alpha_s[esi]
            ef_arr = np.empty(n, dtype=np.float64)
            es_arr = np.empty(n, dtype=np.float64)
            ef_arr[0] = close[0]
            es_arr[0] = close[0]
            for i in range(1, n):
                ef_arr[i] = af * close[i] + (1.0 - af) * ef_arr[i - 1]
                es_arr[i] = as_ * close[i] + (1.0 - as_) * es_arr[i - 1]
            ef_cache[efi, esi] = ef_arr
            es_cache[efi, esi] = es_arr
    return ef_cache, es_cache


# ---------------------------------------------------------------------------
# Pattern occurrence cache per (bp_idx, bs_idx) → bool array
# ---------------------------------------------------------------------------
def build_pat_cache(n: int, df: pd.DataFrame, close: np.ndarray) -> np.ndarray:
    """Pattern cache: all-True (patterns are optional extra filter for now).

    Pattern timestamp alignment with 1h bar timestamps is unreliable due to
    hour-boundary mismatches. Defer pattern filtering to post-scan analysis.
    """
    del df, close
    cache = np.empty((len(BB_PERIODS), len(BB_STDS), n), dtype=bool)
    for pi in range(len(BB_PERIODS)):
        for si in range(len(BB_STDS)):
            cache[pi, si] = True  # all bars pass — patterns used post-filter
    return cache


# ---------------------------------------------------------------------------
# Fast scalar backtest — pure numpy scalars, no pandas access
# ---------------------------------------------------------------------------
def backtest_combo(
    sl_atr: float,
    tp_atr: float,
    max_bars: int,
    pre: dict,
    bb_lower: np.ndarray,
    ema_f: np.ndarray,
    ema_s: np.ndarray,
    has_pat: np.ndarray,
) -> tuple[float, int, float, float, float, float, float, float]:
    """Run backtest. Returns (total_ret, n_trades, wr, avg_w, avg_l, pf, max_dd_pct, expectancy)."""
    c          = pre["close"]
    h          = pre["high"]
    lo         = pre["low"]
    atr        = pre["atr"]
    rsi        = pre["rsi"]
    session_ok = pre["session_ok"]
    n          = pre["n"]
    warmup     = 50

    # Vectorized entry signal for this combo
    entry = (
        (c <= bb_lower * 1.005)
        & (rsi < 35.0)
        & (ema_f > ema_s)
        & session_ok
        & has_pat
    )

    equity = 1.0
    peak   = 1.0
    max_dd = 0.0
    pnl_list: list[float] = []
    HAS_POS = -1          # -1 = flat, else entry bar index
    pos_entry = 0.0
    sl_price = 0.0
    tp_price = 0.0

    for i in range(warmup, n):
        c_i   = c[i]
        lo_i  = lo[i]
        hi_i  = h[i]
        atr_i = atr[i]

        if HAS_POS < 0:  # flat — check entry
            if entry[i]:
                pos_entry = c_i
                sl_price  = c_i - sl_atr * atr_i
                tp_price  = c_i + tp_atr * atr_i
                entry_bar = i
                HAS_POS   = i
        else:  # in position
            bars_held = i - entry_bar
            if lo_i <= sl_price:  # SL
                pnl = (sl_price - pos_entry) / pos_entry * 100.0
                pnl_list.append(pnl)
                equity *= (1.0 + pnl / 100.0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak)
                HAS_POS = -1
            elif hi_i >= tp_price:  # TP
                pnl = (tp_price - pos_entry) / pos_entry * 100.0
                pnl_list.append(pnl)
                equity *= (1.0 + pnl / 100.0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak)
                HAS_POS = -1
            elif bars_held >= max_bars:  # time exit
                pnl = (c_i - pos_entry) / pos_entry * 100.0
                pnl_list.append(pnl)
                equity *= (1.0 + pnl / 100.0)
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak)
                HAS_POS = -1

        if HAS_POS >= 0:  # track open equity
            eq = (c_i - pos_entry) / pos_entry
            equity *= (1.0 + eq / 100.0)
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak)

    total_ret = (equity - 1.0) * 100.0

    if not pnl_list:
        return total_ret, 0, 0.0, 0.0, 0.0, 0.0, max_dd * 100.0, 0.0

    wins   = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    n_t    = len(pnl_list)
    wr     = len(wins) / n_t
    avg_w  = sum(wins)   / len(wins)   if wins   else 0.0
    avg_l  = sum(losses) / len(losses) if losses else 0.0
    pf     = sum(wins) / (abs(sum(losses)) + 1e-12)
    exp    = wr * avg_w + (1.0 - wr) * avg_l

    return total_ret, n_t, wr, avg_w, avg_l, pf, max_dd * 100.0, exp


def make_result(
    bb_period: int, bb_std: float,
    ema_fast: int, ema_slow: int,
    sl_atr: float, tp_atr: float, max_bars: int,
    total_ret: float, n_trades: int, wr: float,
    avg_w: float, avg_l: float, pf: float,
    max_dd: float, exp: float,
) -> ScanResult:
    score = exp * (n_trades ** 0.5) if n_trades > 0 else 0.0
    return ScanResult(
        bb_period=bb_period, bb_std=bb_std,
        ema_fast=ema_fast, ema_slow=ema_slow,
        sl_atr=sl_atr, tp_atr=tp_atr, max_bars=max_bars,
        total_return=total_ret, num_trades=n_trades, win_rate=wr,
        avg_win=avg_w, avg_loss=avg_l, profit_factor=pf,
        max_dd=max_dd, expectancy=exp, score=score,
    )


# ---------------------------------------------------------------------------
# Grid scan
# ---------------------------------------------------------------------------
def run_scan(df: pd.DataFrame) -> list[ScanResult]:
    t0 = time.perf_counter()
    pre = precompute_base(df)
    t1 = time.perf_counter()
    print(f"Base precompute: {t1-t0:.1f}s")

    bb_cache = build_bb_cache(pre["n"], pre["close"])
    t2 = time.perf_counter()
    print(f"BB cache (36 combos): {t2-t1:.1f}s")

    ef_cache, es_cache = build_ema_cache(pre["n"], pre["close"])
    t3 = time.perf_counter()
    print(f"EMA cache (20 combos): {t3-t2:.1f}s")

    pat_cache = build_pat_cache(pre["n"], df, pre["close"])
    t4 = time.perf_counter()
    print(f"Pattern cache (36 combos): {t4-t3:.1f}s")

    results: list[ScanResult] = []
    total_combos = sum(
        1 for bp in BB_PERIODS for bs in BB_STDS
        for ef in EMA_FASTS for es in EMA_SLOWS
        for sl in SL_ATRS for tp in TP_ATRS for mb in MAX_BARS_LIST
        if ef < es and tp > sl
    )
    print(f"Grid: {total_combos} combos")
    scan_t0 = time.perf_counter()
    count = 0

    for bpi, bp in enumerate(BB_PERIODS):
        for bsi, bs in enumerate(BB_STDS):
            bb_low   = bb_cache[bpi, bsi]
            has_pat  = pat_cache[bpi, bsi]

            for efi, ef in enumerate(EMA_FASTS):
                for esi, es in enumerate(EMA_SLOWS):
                    if ef >= es:
                        continue
                    ema_f = ef_cache[efi, esi]
                    ema_s = es_cache[efi, esi]

                    for sl in SL_ATRS:
                        for tp in TP_ATRS:
                            if tp <= sl:
                                continue
                            for mb in MAX_BARS_LIST:
                                ret, n_t, wr, aw, al, pf, dd, exp = backtest_combo(
                                    sl, tp, mb, pre, bb_low, ema_f, ema_s, has_pat,
                                )
                                results.append(make_result(
                                    bp, bs, ef, es, sl, tp, mb,
                                    ret, n_t, wr, aw, al, pf, dd, exp,
                                ))
                                count += 1

    scan_elapsed = time.perf_counter() - scan_t0
    total_elapsed = time.perf_counter() - t0
    print(f"Scan {count} combos in {scan_elapsed:.1f}s "
          f"({scan_elapsed/count*1000:.2f}ms/combo)")
    print(f"Total time: {total_elapsed:.1f}s")
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def show_top(results: list[ScanResult], n: int = 30) -> None:
    filtered = [
        r for r in results
        if r.num_trades >= 25 and r.win_rate > 0.50 and r.max_dd < 10
    ]
    filtered.sort(key=lambda r: r.score, reverse=True)
    top = filtered[:n]

    print()
    hdr = (f"{'BB_p':>5} {'BB_s':>5} {'EF':>3} {'ES':>3} "
           f"{'SL':>4} {'TP':>4} {'MB':>3} "
           f"{'Trd':>5} {'WR%':>5} {'AvgW':>6} {'AvgL':>6} "
           f"{'PF':>5} {'Ret%':>7} {'DD%':>5} {'Score':>7}")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))
    for r in top:
        row = (f"{r.bb_period:>5} {r.bb_std:>5.1f} {r.ema_fast:>3} {r.ema_slow:>3} "
               f"{r.sl_atr:>4.1f} {r.tp_atr:>4.1f} {r.max_bars:>3} "
               f"{r.num_trades:>5} {r.win_rate*100:>5.1f} "
               f"{r.avg_win:>+6.3f} {r.avg_loss:>+6.3f} "
               f"{r.profit_factor:>5.2f} {r.total_return:>+7.2f} "
               f"{r.max_dd:>5.1f} {r.score:>7.3f}")
        print(row)

    out = [{
        "bb_period": r.bb_period, "bb_std": round(r.bb_std, 2),
        "ema_fast": r.ema_fast, "ema_slow": r.ema_slow,
        "sl_atr": r.sl_atr, "tp_atr": r.tp_atr, "max_bars": r.max_bars,
        "num_trades": r.num_trades, "win_rate": round(r.win_rate, 4),
        "avg_win": round(r.avg_win, 4), "avg_loss": round(r.avg_loss, 4),
        "profit_factor": round(r.profit_factor, 4),
        "total_return": round(r.total_return, 2),
        "max_dd": round(r.max_dd, 2), "score": round(r.score, 4),
    } for r in top]
    Path("scripts/top_configs.json").write_text(json.dumps(out, indent=2))
    print("\nTop configs saved to scripts/top_configs.json")


def main() -> None:
    data_path = Path(__file__).parent.parent / "backtest_data" / "candles" / "xauusd_1h.parquet"
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"Loaded {len(df)} bars: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")
    results = run_scan(df)
    show_top(results)


if __name__ == "__main__":
    main()
