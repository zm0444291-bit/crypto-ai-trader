#!/usr/bin/env python3
"""
scan_kdj_range.py — KDJ + MACD 区间反转策略扫描 (精简网格版)
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq  # noqa: F401

sys.path.insert(0, str(Path(__file__).parent.parent))

INITIAL_EQUITY = 10_000.0
ATR_PERIOD = 14
WARMUP = 50

# 精简网格
K_PERIODS   = [9, 12]
D_PERIODS   = [3, 5]
KDJ_OS      = [20, 25]
KDJ_OB      = [75, 80]
SMOOTH_K    = [2, 3]
MACD_FAST   = [10, 12]
MACD_SLOW   = [20, 26]
MACD_SIGNAL = [9]
SL_ATR_LIST = [1.0, 1.5, 2.0]
TP_ATR_LIST = [2.0, 2.5, 3.0]
MAX_BARS    = [3, 4, 5]


@dataclass
class Result:
    mode: str
    kp: int; dp: int; sk: int; k_os: int; k_ob: int
    mf: int; ms: int; msi: int
    sl: float; tp: float; mb: int
    total_return: float; ann_return: float; num_trades: int
    win_rate: float; avg_win: float; avg_loss: float; profit_factor: float
    max_dd: float; sharpe: float; score: float
    longs: int; shorts: int; avg_bars: float


def load_data() -> pd.DataFrame:
    data_path = Path(__file__).parent.parent / "backtest_data" / "candles" / "xauusd_1h.parquet"
    df = pq.read_table(data_path).to_pandas()
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def prepare(df: pd.DataFrame) -> dict:
    c = df["close"].astype(float).values
    h = df["high"].astype(float).values
    lo = df["low"].astype(float).values
    n  = len(df)

    tr1 = h - lo
    tr2 = np.abs(h - np.roll(c, 1)); tr2[0] = tr1[0]
    tr3 = np.abs(lo - np.roll(c, 1)); tr3[0] = tr1[0]
    tr  = np.maximum(np.maximum(tr1, tr2), tr3)
    atr = np.full(n, np.nan)
    alpha = 2.0 / (ATR_PERIOD + 1)
    s = 0.0
    for i in range(n):
        if i < ATR_PERIOD:
            s += tr[i]
            if i == ATR_PERIOD - 1:
                atr[i] = s / ATR_PERIOD
        else:
            atr[i] = atr[i-1] + alpha * (tr[i] - atr[i-1])

    ts = pd.to_datetime(df["timestamp"], utc=True)
    hour_utc = ts.dt.hour + ts.dt.minute / 60.0
    session_ok = np.array([h_ >= 13.5 and h_ <= 21.0 or h_ <= 3.0 for h_ in hour_utc])

    return {"close": c, "high": h, "low": lo, "atr": atr, "session_ok": session_ok, "n": n}


def compute_kdj(c: np.ndarray, h: np.ndarray, lo: np.ndarray,
               k_period: int, d_period: int, smooth_k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(c)
    rsv = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        max_high = np.max(h[i - k_period + 1:i + 1])
        min_low = np.min(lo[i - k_period + 1:i + 1])
        denom = max_high - min_low
        rsv[i] = 0.0 if denom == 0 else 100 * (c[i] - min_low) / denom

    k = pd.Series(rsv).fillna(50.0).rolling(smooth_k, min_periods=1).mean().values
    d = pd.Series(k).rolling(d_period, min_periods=1).mean().values
    j = 3 * k - 2 * d
    return k, d, j


def compute_macd(c: np.ndarray, fast: int, slow: int, signal: int) -> np.ndarray:
    def ema(arr: np.ndarray, p: int) -> np.ndarray:
        n = len(arr)
        out = np.zeros(n)
        a = 2.0 / (p + 1)
        s = float(arr[0])
        out[0] = s
        for i in range(1, n):
            s = s + a * (arr[i] - s)
            out[i] = s
        return out

    macd_line = ema(c, fast) - ema(c, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line


def bt_kdj_range(
    pre: dict,
    k_period: int, d_period: int, smooth_k: int,
    k_os: int, k_ob: int,
    macd_fast: int, macd_slow: int, macd_sig: int,
    sl_atr: float, tp_atr: float, max_bars: int,
) -> tuple:
    c = pre["close"]; lo = pre["low"]; h = pre["high"]
    atr = pre["atr"]; session_ok = pre["session_ok"]
    n = pre["n"]

    j_vals, _, _ = compute_kdj(c, h, lo, k_period, d_period, smooth_k)
    hist = compute_macd(c, macd_fast, macd_slow, macd_sig)

    eq = INITIAL_EQUITY; peak = eq; max_dd = 0.0
    pnl_list: list[float] = []
    bars_list: list[int] = []
    longs = 0; shorts = 0
    pos = 0; entry_p = 0.0; sl_p = 0.0; tp_p = 0.0; entry_bar = 0

    for i in range(WARMUP, n):
        c_i = c[i]; lo_i = lo[i]; hi_i = h[i]
        j_i = j_vals[i]; j_prev = j_vals[i-1]
        hist_i = hist[i]

        if pos == 0:
            if not session_ok[i]:
                continue

            long_cond  = j_i < k_os and j_prev >= k_os and hist_i > 0
            short_cond = j_i > k_ob and j_prev <= k_ob and hist_i < 0

            if long_cond:
                pos = 1; entry_p = c_i
                sl_p = c_i - sl_atr * atr[i]
                tp_p = c_i + tp_atr * atr[i]
                entry_bar = i; longs += 1
            elif short_cond:
                pos = -1; entry_p = c_i
                sl_p = c_i + sl_atr * atr[i]
                tp_p = c_i - tp_atr * atr[i]
                entry_bar = i; shorts += 1

        elif pos == 1:
            bars = i - entry_bar
            rev_cond = j_vals[i-1] <= k_ob and j_vals[i] > k_ob

            if lo_i <= sl_p:
                pct = (sl_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0
            elif hi_i >= tp_p:
                pct = (tp_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0
            elif rev_cond or bars >= max_bars:
                pct = (c_i - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0

        elif pos == -1:
            bars = i - entry_bar
            rev_cond = j_vals[i-1] >= k_os and j_vals[i] < k_os

            if hi_i >= sl_p:
                pct = (entry_p - sl_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0
            elif lo_i <= tp_p:
                pct = (entry_p - tp_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0
            elif rev_cond or bars >= max_bars:
                pct = (entry_p - c_i) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0

    total_ret = (eq - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    ann_ret = total_ret / (n / (252 * 24)) if n > 0 else 0.0
    n_t = len(pnl_list)
    if n_t == 0:
        return (0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0, 0.0, 0.0)
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    wr = len(wins) / n_t
    avg_w = sum(wins)/len(wins) if wins else 0.0
    avg_l = sum(losses)/len(losses) if losses else 0.0
    pf = sum(wins) / (abs(sum(losses)) + 1e-12)
    avg_bars = sum(bars_list)/n_t
    ret_per_trade = total_ret / n_t
    sharpe = ret_per_trade / (abs(max_dd*100) + 0.1)
    score = ret_per_trade * (n_t ** 0.4) / (abs(max_dd*100) + 0.1)
    return (total_ret, ann_ret, n_t, wr, avg_w, avg_l, pf,
            longs, shorts, avg_bars, sharpe, max_dd*100, score)


def main() -> None:
    print("Loading data...")
    df = load_data()
    print(f"  {len(df)} bars, {df['timestamp'].min()} → {df['timestamp'].max()}")

    print("Preparing indicators...")
    pre = prepare(df)

    total = sum(
        1 for kp in K_PERIODS
          for dp in D_PERIODS
          for sk in SMOOTH_K
          for os in KDJ_OS
          for ob in KDJ_OB
          if os < ob
          for mf in MACD_FAST
          for ms in MACD_SLOW
          if ms > mf
          for _si in MACD_SIGNAL
          for sl in SL_ATR_LIST
          for tp in TP_ATR_LIST
          if tp > sl
          for mb in MAX_BARS
    )
    print(f"Scanning {total} valid combos...")

    results: list[Result] = []
    done = 0
    t0 = time.time()

    for kp in K_PERIODS:
        for dp in D_PERIODS:
            for sk in SMOOTH_K:
                for os in KDJ_OS:
                    for ob in KDJ_OB:
                        if os >= ob:
                            continue
                        for mf in MACD_FAST:
                            for ms in MACD_SLOW:
                                if ms <= mf:
                                    continue
                                for si in MACD_SIGNAL:
                                    for sl in SL_ATR_LIST:
                                        for tp in TP_ATR_LIST:
                                            if tp <= sl:
                                                continue
                                            for mb in MAX_BARS:
                                                ret, ann, n_t, wr, aw, al, pf, longs, shorts, avg_b, sh, dd, sc = bt_kdj_range(
                                                    pre, kp, dp, sk, os, ob,
                                                    mf, ms, si, sl, tp, mb,
                                                )
                                                results.append(Result(
                                                    mode="KDJ_RANGE",
                                                    kp=kp, dp=dp, sk=sk, k_os=os, k_ob=ob,
                                                    mf=mf, ms=ms, msi=si,
                                                    sl=sl, tp=tp, mb=mb,
                                                    total_return=ret, ann_return=ann,
                                                    num_trades=n_t, win_rate=wr,
                                                    avg_win=aw, avg_loss=al, profit_factor=pf,
                                                    max_dd=dd, sharpe=sh, score=sc,
                                                    longs=longs, shorts=shorts, avg_bars=avg_b,
                                                ))
                                                done += 1
                                                if done % 1000 == 0:
                                                    elapsed = time.time() - t0
                                                    eta = (total - done) / (done/elapsed)
                                                    print(f"  {done}/{total} ({done/total*100:.1f}%) — ETA {eta:.0f}s")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s — {done} combos")

    results.sort(key=lambda r: r.score, reverse=True)
    print("\n=== TOP 10 KDJ RANGE ===")
    for i, x in enumerate(results[:10]):
        print(f"\n{i+1}. Score={x.score:.3f} PF={x.profit_factor:.2f} WR={x.win_rate:.1%} "
              f"Trades={x.num_trades} Ann={x.ann_return:.1%} DD={x.max_dd:.1%}")
        print(f"   K({x.kp},{x.dp}) smooth={x.sk} OS={x.k_os} OB={x.k_ob}")
        print(f"   MACD({x.mf},{x.ms},{x.msi}) SL={x.sl} TP={x.tp} MB={x.mb}")
        print(f"   Longs={x.longs} Shorts={x.shorts} AvgBars={x.avg_bars:.1f}")

    out_path = Path(__file__).parent / "kdj_range_results.json"
    with open(out_path, "w") as f:
        json.dump([{
            "mode": r.mode,
            "params": {"kp": r.kp, "dp": r.dp, "sk": r.sk, "k_os": r.k_os, "k_ob": r.k_ob,
                       "mf": r.mf, "ms": r.ms, "msi": r.msi, "sl": r.sl, "tp": r.tp, "mb": r.mb},
            "total_return": r.total_return, "ann_return": r.ann_return,
            "num_trades": r.num_trades, "win_rate": r.win_rate,
            "avg_win": r.avg_win, "avg_loss": r.avg_loss,
            "profit_factor": r.profit_factor, "max_dd": r.max_dd,
            "sharpe": r.sharpe, "score": r.score,
            "longs": r.longs, "shorts": r.shorts, "avg_bars": r.avg_bars,
        } for r in results], f, indent=2)
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
