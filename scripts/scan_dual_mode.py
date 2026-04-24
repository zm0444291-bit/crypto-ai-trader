#!/usr/bin/env python3
"""
scan_dual_mode.py — 短线双模式参数扫描

两种完全不同的短线逻辑:
  RANGE_MODE  (震荡区间短线):
    — 原理: BB 收口 + RSI 极端值 = 区间极点 → 反转交易
    — 做多: price <= BB_lower AND RSI < 35
    — 做空: price >= BB_upper AND RSI > 65
    — 退出: TP/SL/时间止损

  TREND_MODE  (趋势内短线):
    — 原理: EMA 多头排列 + ADX 确认趋势 → 顺势交易
    — 做多: EMA_fast > EMA_slow AND ADX > 20 AND ATR 在合理范围
    — 做空: EMA_fast < EMA_slow AND ADX > 20
    — 退出: 反向 EMA 死叉 / SL / 时间止损

每种模式各做多空，每次只持有1个仓位。
先用 regime detector 把数据分段，分别在对应 regime 下回测。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODE: Literal["RANGE", "TREND", "BOTH"] = "BOTH"

# RANGE mode grids
R_BB_PERIODS = [5, 7, 8, 10, 12]
R_BB_STDS    = [1.5, 2.0, 2.5]
R_RSI_OS     = [25, 30, 35]        # oversold threshold for long
R_RSI_OB     = [65, 70, 75]        # overbought threshold for short
R_SL_ATRS    = [1.0, 1.3, 1.5, 2.0]
R_TP_ATRS    = [1.5, 2.0, 2.5, 3.0]
R_MAX_BARS   = [3, 4, 5, 6]

# TREND mode grids
T_EMA_FAST   = [5, 8, 10, 12, 15]
T_EMA_SLOW   = [20, 30, 50]
T_ADX_THRESH = [18, 20, 22, 25]   # minimum ADX to confirm trend
T_SL_ATRS    = [1.5, 2.0, 2.5, 3.0]
T_TP_ATRS    = [2.0, 2.5, 3.0, 3.5]
T_MAX_BARS   = [4, 5, 6, 8]

# Common
ATR_PERIOD   = 14
INITIAL_EQUITY = 10_000.0

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------
@dataclass
class Result:
    mode: str
    # params
    p1: float; p2: float; p3: float; p4: float; p5: float; p6: float
    # metrics
    total_return: float
    ann_return: float
    num_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_dd: float
    sharpe: float
    score: float
    longs: int
    shorts: int
    avg_bars: float


def precompute(df: pd.DataFrame) -> dict:
    c = df["close"].astype(np.float64).values
    h = df["high"].astype(np.float64).values
    lo = df["low"].astype(np.float64).values
    n = len(df)

    # ATR
    pc = np.empty(n, dtype=np.float64); pc[0] = c[0]; pc[1:] = c[:-1]
    tr1 = h - lo; tr2 = np.abs(h - pc); tr3 = np.abs(lo - pc)
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    atr = _roll_mean(tr, 14)

    # RSI
    d = np.diff(c, prepend=c[0])
    gain = np.where(d > 0, d, 0.0); loss = np.where(d < 0, -d, 0.0)
    avg_g = _roll_mean(gain, 14); avg_l = _roll_mean(loss, 14)
    rsi = 100.0 - 100.0 / (1.0 + avg_g / (avg_l + 1e-12))

    # EMA for regime detection (vectorized)
    EMA_F_DET = 10; EMA_S_DET = 30
    ef_det = np.empty(n, dtype=np.float64); ef_det[0] = c[0]
    es_det = np.empty(n, dtype=np.float64); es_det[0] = c[0]
    af_det = 2.0 / (EMA_F_DET + 1); as_det = 2.0 / (EMA_S_DET + 1)
    for i in range(1, n):
        ef_det[i] = af_det * c[i] + (1 - af_det) * ef_det[i-1]
        es_det[i] = as_det * c[i] + (1 - as_det) * es_det[i-1]

    # ADX for regime detection (vectorized)
    plus_dm = np.diff(h, prepend=h[0])
    minus_dm = -np.diff(lo, prepend=lo[0])
    plus_dm = np.where(plus_dm > minus_dm, plus_dm, 0.0)
    minus_dm = np.where(minus_dm > plus_dm, minus_dm, 0.0)
    s_plus = np.empty(n, dtype=np.float64); s_minus = np.empty(n, dtype=np.float64)
    s_plus[0] = plus_dm[0]; s_minus[0] = minus_dm[0]
    for i in range(1, n):
        s_plus[i] = (13/14) * s_plus[i-1] + plus_dm[i] / 14
        s_minus[i] = (13/14) * s_minus[i-1] + minus_dm[i] / 14
    dmi_plus = 100 * s_plus / (atr + 1e-12)
    dmi_minus = 100 * s_minus / (atr + 1e-12)
    # ADX: DX smoothed with Wilder's EMA via pandas ewm (span=14, adjust=False)
    dx = 100.0 * np.abs(dmi_plus - dmi_minus) / (dmi_plus + dmi_minus + 1e-12)
    adx_det = pd.Series(dx).ewm(span=14, adjust=False).mean().values.astype(np.float64)

    # Regime classification (vectorized, O(n))
    ema_spread = np.abs(ef_det - es_det) / (es_det + 1e-12)
    is_trending = adx_det >= 20.0
    bull = is_trending & (ef_det > es_det)
    bear = is_trending & (ef_det < es_det)
    clean_range = ~is_trending & (ema_spread < 0.005)
    vol_chop = ~is_trending & (ema_spread >= 0.005)
    # 1=BULL_TREND, 2=BEAR_TREND, 3=RANGE_BOUND, 4=VOLATILE_CHOP
    regime_arr = np.zeros(n, dtype=np.int8)
    regime_arr[bull]       = 1
    regime_arr[bear]       = 2
    regime_arr[clean_range] = 3
    regime_arr[vol_chop]   = 4

    # Session mask: block 11-14 UTC (low-liquidity)
    ts = pd.to_datetime(df["timestamp"])
    hours = np.array([t.hour for t in ts], dtype=np.int8)
    session_ok = ~((hours >= 11) & (hours < 14))

    return {
        "close": c, "high": h, "low": lo,
        "atr": atr, "rsi": rsi,
        "session_ok": session_ok,
        "regime": regime_arr,
        "adx": adx_det,
        "ema_fast_det": ef_det,
        "ema_slow_det": es_det,
        "n": n,
    }


def _roll_mean(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr); out = np.empty(n, dtype=np.float64)
    cs = np.cumsum(arr)
    out[:window] = np.nan
    out[window:] = (cs[window:] - cs[:-window]) / window
    return out


def _roll_var(close: np.ndarray, period: int) -> np.ndarray:
    mean = _roll_mean(close, period)
    mean_sq = _roll_mean(close * close, period)
    var = mean_sq - mean * mean
    var[:period - 1] = np.nan
    return var


# ---------------------------------------------------------------------------
# Build indicator caches
# ---------------------------------------------------------------------------
def build_bb_cache(n: int, close: np.ndarray):
    cache_mid = np.empty((len(R_BB_PERIODS), len(R_BB_STDS), n), dtype=np.float64)
    cache_lo  = np.empty((len(R_BB_PERIODS), len(R_BB_STDS), n), dtype=np.float64)
    cache_hi  = np.empty((len(R_BB_PERIODS), len(R_BB_STDS), n), dtype=np.float64)
    for pi, bp in enumerate(R_BB_PERIODS):
        mid = _roll_mean(close, bp)
        std = np.sqrt(_roll_var(close, bp))
        for si, bs in enumerate(R_BB_STDS):
            cache_mid[pi, si] = mid
            cache_lo[pi, si]  = mid - std * bs
            cache_hi[pi, si]  = mid + std * bs
    return cache_lo, cache_mid, cache_hi


def build_ema_cache(n: int, close: np.ndarray):
    """Returns (fast_cache, slow_cache) each (len(T_EMA_FAST), len(T_EMA_SLOW), n)."""
    fc = np.empty((len(T_EMA_FAST), len(T_EMA_SLOW), n), dtype=np.float64)
    sc = np.empty((len(T_EMA_FAST), len(T_EMA_SLOW), n), dtype=np.float64)
    alpha_f = np.array([2.0 / (f + 1) for f in T_EMA_FAST])
    alpha_s = np.array([2.0 / (s + 1) for s in T_EMA_SLOW])
    for efi in range(len(T_EMA_FAST)):
        af = alpha_f[efi]
        for esi in range(len(T_EMA_SLOW)):
            as_ = alpha_s[esi]
            ef_arr = np.empty(n, dtype=np.float64)
            es_arr = np.empty(n, dtype=np.float64)
            ef_arr[0] = close[0]; es_arr[0] = close[0]
            for i in range(1, n):
                ef_arr[i] = af * close[i] + (1.0 - af) * ef_arr[i - 1]
                es_arr[i] = as_ * close[i] + (1.0 - as_) * es_arr[i - 1]
            fc[efi, esi] = ef_arr
            sc[efi, esi] = es_arr
    return fc, sc





# ---------------------------------------------------------------------------
# Backtest RANGE mode (long + short)
# ---------------------------------------------------------------------------
def bt_range(
    pre: dict,
    bb_lo, bb_mid, bb_hi,       # (R_BB_PERIODS, R_BB_STDS, n)
    p_rsi_os, p_rsi_ob,
    p_sl, p_tp, p_max_bars,
) -> tuple:
    c   = pre["close"]; lo = pre["low"]; h = pre["high"]
    atr = pre["atr"]; rsi = pre["rsi"]
    session_ok = pre["session_ok"]
    regime = pre["regime"]
    n = pre["n"]
    WARMUP = 50

    eq = INITIAL_EQUITY; peak = eq; max_dd = 0.0
    pnl_list: list[float] = []
    bars_held_list: list[int] = []
    longs = 0; shorts = 0
    pos = 0      # 0=flat, 1=long, -1=short
    entry_p = 0.0; sl_p = 0.0; tp_p = 0.0; entry_bar = 0

    for i in range(WARMUP, n):
        c_i = c[i]; lo_i = lo[i]; hi_i = h[i]
        atr_i = atr[i]; rsi_i = rsi[i]

        if pos == 0:
            in_range_regime = regime[i] == 3   # RANGE_BOUND
            if not in_range_regime and MODE == "RANGE":
                continue

            # LONG: BB lower touch + RSI oversold
            if c_i <= bb_lo[i] * 1.003 and rsi_i < p_rsi_os and session_ok[i]:
                pos = 1; entry_p = c_i
                sl_p = c_i - p_sl * atr_i
                tp_p = c_i + p_tp * atr_i
                entry_bar = i; longs += 1
            # SHORT: BB upper touch + RSI overbought
            elif c_i >= bb_hi[i] * 0.997 and rsi_i > p_rsi_ob and session_ok[i]:
                pos = -1; entry_p = c_i
                sl_p = c_i + p_sl * atr_i
                tp_p = c_i - p_tp * atr_i
                entry_bar = i; shorts += 1

        elif pos == 1:
            bars = i - entry_bar
            hit_sl = lo_i <= sl_p
            hit_tp = hi_i >= tp_p
            hit_tm = bars >= p_max_bars

            if hit_sl:
                pct = (sl_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif hit_tp:
                pct = (tp_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif hit_tm:
                pct = (c_i - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0

        elif pos == -1:
            bars = i - entry_bar
            hit_sl = hi_i >= sl_p
            hit_tp = lo_i <= tp_p
            hit_tm = bars >= p_max_bars

            if hit_sl:
                pct = (entry_p - sl_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif hit_tp:
                pct = (entry_p - tp_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif hit_tm:
                pct = (entry_p - c_i) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0

    total_ret = (eq - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    ann_ret = total_ret / (n / (252 * 24)) if n > 0 else 0.0
    n_t = len(pnl_list)
    if n_t == 0:
        return (total_ret, ann_ret, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, max_dd*100, 0.0, 0.0)
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    wr = len(wins) / n_t
    avg_w = sum(wins)/len(wins) if wins else 0.0
    avg_l = sum(losses)/len(losses) if losses else 0.0
    pf = sum(wins) / (abs(sum(losses)) + 1e-12)
    avg_bars = sum(bars_held_list)/n_t if bars_held_list else 0.0
    ret_per_trade = total_ret / n_t if n_t > 0 else 0.0
    sharpe = ret_per_trade / (abs(max_dd*100) + 0.1) if max_dd > 0 else 0.0
    score = ret_per_trade * (n_t ** 0.4) / (abs(max_dd*100) + 0.1) if max_dd > 0 else 0.0
    return (
        total_ret, ann_ret, n_t, wr, avg_w, avg_l, pf,
        longs, shorts, avg_bars, sharpe, max_dd*100, score,
    )


# ---------------------------------------------------------------------------
# Backtest TREND mode (long + short)
# ---------------------------------------------------------------------------
def bt_trend(
    pre: dict,
    ema_f_cache, ema_s_cache,
    ef_idx, es_idx,
    p_adx_thresh, p_sl, p_tp, p_max_bars,
) -> tuple:
    c = pre["close"]; lo = pre["low"]; h = pre["high"]
    atr = pre["atr"]; adx = pre["adx"]
    session_ok = pre["session_ok"]
    regime = pre["regime"]
    n = pre["n"]
    WARMUP = 50

    ema_f = ema_f_cache[ef_idx, es_idx]
    ema_s = ema_s_cache[ef_idx, es_idx]

    eq = INITIAL_EQUITY; peak = eq; max_dd = 0.0
    pnl_list: list[float] = []
    bars_held_list: list[int] = []
    longs = 0; shorts = 0
    pos = 0; entry_p = 0.0; sl_p = 0.0; tp_p = 0.0; entry_bar = 0

    for i in range(WARMUP, n):
        c_i = c[i]; lo_i = lo[i]; hi_i = h[i]
        atr_i = atr[i]; adx_i = adx[i]

        if pos == 0:
            in_trend_regime = regime[i] in (1, 2)   # BULL_TREND or BEAR_TREND
            if not in_trend_regime and MODE == "TREND":
                continue

            ef_i = ema_f[i]; es_i = ema_s[i]
            ef_prev = ema_f[i-1] if i > WARMUP else ef_i
            es_prev = ema_s[i-1] if i > WARMUP else es_i

            bull_cross = ef_prev <= es_prev and ef_i > es_i
            bear_cross = ef_prev >= es_prev and ef_i < es_i

            # LONG: golden cross + ADX confirmation
            if bull_cross and adx_i >= p_adx_thresh and session_ok[i]:
                pos = 1; entry_p = c_i
                sl_p = c_i - p_sl * atr_i
                tp_p = c_i + p_tp * atr_i
                entry_bar = i; longs += 1
            # SHORT: death cross + ADX confirmation
            elif bear_cross and adx_i >= p_adx_thresh and session_ok[i]:
                pos = -1; entry_p = c_i
                sl_p = c_i + p_sl * atr_i
                tp_p = c_i - p_tp * atr_i
                entry_bar = i; shorts += 1

        elif pos == 1:
            bars = i - entry_bar
            ef_i = ema_f[i]; es_i = ema_s[i]
            ef_prev = ema_f[i-1]; es_prev = ema_s[i-1]
            # Exit on death cross
            dead_cross = ef_prev >= es_prev and ef_i < es_i

            if lo_i <= sl_p:
                pct = (sl_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif hi_i >= tp_p:
                pct = (tp_p - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif dead_cross or bars >= p_max_bars:
                pct = (c_i - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0

        elif pos == -1:
            bars = i - entry_bar
            ef_i = ema_f[i]; es_i = ema_s[i]
            ef_prev = ema_f[i-1]; es_prev = ema_s[i-1]
            gold_cross = ef_prev <= es_prev and ef_i > es_i

            if hi_i >= sl_p:
                pct = (entry_p - sl_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif lo_i <= tp_p:
                pct = (entry_p - tp_p) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0
            elif gold_cross or bars >= p_max_bars:
                pct = (entry_p - c_i) / entry_p * 100
                pnl_list.append(pct); bars_held_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak)
                pos = 0

    total_ret = (eq - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    ann_ret = total_ret / (n / (252 * 24)) if n > 0 else 0.0
    n_t = len(pnl_list)
    if n_t == 0:
        return (total_ret, ann_ret, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, max_dd*100, 0.0, 0.0)
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    wr = len(wins) / n_t
    avg_w = sum(wins)/len(wins) if wins else 0.0
    avg_l = sum(losses)/len(losses) if losses else 0.0
    pf = sum(wins) / (abs(sum(losses)) + 1e-12)
    avg_bars = sum(bars_held_list)/n_t if bars_held_list else 0.0
    ret_per_trade = total_ret / n_t if n_t > 0 else 0.0
    sharpe = ret_per_trade / (abs(max_dd*100) + 0.1)
    score = ret_per_trade * (n_t ** 0.4) / (abs(max_dd*100) + 0.1)
    return (
        total_ret, ann_ret, n_t, wr, avg_w, avg_l, pf,
        longs, shorts, avg_bars, sharpe, max_dd*100, score,
    )


# ---------------------------------------------------------------------------
# Scan RANGE combos
# ---------------------------------------------------------------------------
def scan_range(pre: dict, bb_lo, bb_mid, bb_hi) -> list[Result]:
    results: list[Result] = []
    total = (
        len(R_BB_PERIODS) * len(R_BB_STDS) *
        len(R_RSI_OS) * len(R_RSI_OB) *
        len(R_SL_ATRS) * len(R_TP_ATRS) *
        len(R_MAX_BARS)
    )
    done = 0

    for pi, bp in enumerate(R_BB_PERIODS):
        for si, bs in enumerate(R_BB_STDS):
            bb_lo_i = bb_lo[pi, si]; bb_hi_i = bb_hi[pi, si]
            for rsi_os in R_RSI_OS:
                for rsi_ob in R_RSI_OB:
                    if rsi_os >= rsi_ob:
                        continue
                    for sl in R_SL_ATRS:
                        for tp in R_TP_ATRS:
                            if tp <= sl:
                                continue
                            for mb in R_MAX_BARS:
                                ret, ann, n_t, wr, aw, al, pf, longs, shorts, avg_b, sh, dd, sc = bt_range(
                                    pre, bb_lo_i, bb_mid[pi,si], bb_hi_i,
                                    rsi_os, rsi_ob, sl, tp, mb,
                                )
                                results.append(Result(
                                    mode="RANGE",
                                    p1=bp, p2=bs, p3=rsi_os, p4=rsi_ob, p5=sl, p6=tp,
                                    total_return=ret, ann_return=ann,
                                    num_trades=n_t, win_rate=wr,
                                    avg_win=aw, avg_loss=al, profit_factor=pf,
                                    max_dd=dd, sharpe=sh, score=sc,
                                    longs=longs, shorts=shorts, avg_bars=avg_b,
                                ))
                                done += 1
    print(f"  RANGE scan: {done}/{total} combos done")
    return results


# ---------------------------------------------------------------------------
# Scan TREND combos
# ---------------------------------------------------------------------------
def scan_trend(pre: dict, ema_f_cache, ema_s_cache) -> list[Result]:
    results: list[Result] = []
    total = (
        len(T_EMA_FAST) * len(T_EMA_SLOW) *
        len(T_ADX_THRESH) *
        len(T_SL_ATRS) * len(T_TP_ATRS) *
        len(T_MAX_BARS)
    )
    done = 0

    for efi in range(len(T_EMA_FAST)):
        for esi in range(len(T_EMA_SLOW)):
            if T_EMA_FAST[efi] >= T_EMA_SLOW[esi]:
                continue
            for adx_th in T_ADX_THRESH:
                for sl in T_SL_ATRS:
                    for tp in T_TP_ATRS:
                        if tp <= sl:
                            continue
                        for mb in T_MAX_BARS:
                            ret, ann, n_t, wr, aw, al, pf, longs, shorts, avg_b, sh, dd, sc = bt_trend(
                                pre, ema_f_cache, ema_s_cache,
                                efi, esi, adx_th, sl, tp, mb,
                            )
                            results.append(Result(
                                mode="TREND",
                                p1=T_EMA_FAST[efi], p2=T_EMA_SLOW[esi],
                                p3=adx_th, p4=sl, p5=tp, p6=mb,
                                total_return=ret, ann_return=ann,
                                num_trades=n_t, win_rate=wr,
                                avg_win=aw, avg_loss=al, profit_factor=pf,
                                max_dd=dd, sharpe=sh, score=sc,
                                longs=longs, shorts=shorts, avg_bars=avg_b,
                            ))
                            done += 1
    print(f"  TREND scan: {done}/{total} combos done")
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def report(results: list[Result], mode: str, top_n: int = 20) -> None:
    fltr = [r for r in results if r.num_trades >= 15 and r.max_dd < 15]
    fltr.sort(key=lambda r: r.score, reverse=True)
    top = fltr[:top_n]

    print()
    print(f"{'='*110}")
    print(f"  {mode} MODE — Top {len(top)} configs")
    print(f"{'='*110}")

    if mode == "RANGE":
        hdr = (f"{'BB_p':>5} {'BB_s':>5} {'RSI_OS':>7} {'RSI_OB':>7} "
               f"{'SL':>4} {'TP':>4} {'MB':>3} "
               f"{'Trd':>5} {'L':>3} {'S':>3} "
               f"{'WR%':>5} {'AvgW':>6} {'AvgL':>6} "
               f"{'PF':>5} {'Ret%':>8} {'DD%':>6} {'Score':>7}")
    else:
        hdr = (f"{'EF':>3} {'ES':>3} {'ADX':>4} "
               f"{'SL':>4} {'TP':>4} {'MB':>3} "
               f"{'Trd':>5} {'L':>3} {'S':>3} "
               f"{'WR%':>5} {'AvgW':>6} {'AvgL':>6} "
               f"{'PF':>5} {'Ret%':>8} {'DD%':>6} {'Score':>7}")

    print(hdr)
    print("-" * len(hdr))
    for r in top:
        if mode == "RANGE":
            row = (f"{int(r.p1):>5} {r.p2:>5.1f} {int(r.p3):>7} {int(r.p4):>7} "
                   f"{r.p5:>4.1f} {r.p6:>4.1f} {int(r.num_trades/100):>3} "
                   f"{r.num_trades:>5} {r.longs:>3} {r.shorts:>3} "
                   f"{r.win_rate*100:>5.1f} {r.avg_win:>+6.3f} {r.avg_loss:>+6.3f} "
                   f"{r.profit_factor:>5.2f} {r.total_return:>+8.2f} {r.max_dd:>6.1f} {r.score:>7.3f}")
        else:
            row = (f"{int(r.p1):>3} {int(r.p2):>3} {int(r.p3):>4} "
                   f"{r.p4:>4.1f} {r.p5:>4.1f} {int(r.p6):>3} "
                   f"{r.num_trades:>5} {r.longs:>3} {r.shorts:>3} "
                   f"{r.win_rate*100:>5.1f} {r.avg_win:>+6.3f} {r.avg_loss:>+6.3f} "
                   f"{r.profit_factor:>5.2f} {r.total_return:>+8.2f} {r.max_dd:>6.1f} {r.score:>7.3f}")
        print(row)

    return top


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    t0 = time.perf_counter()

    data_path = Path(__file__).parent.parent / "backtest_data" / "candles" / "xauusd_1h.parquet"
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"Loaded {len(df)} bars: {df['timestamp'].iloc[0]} → {df['timestamp'].iloc[-1]}")

    # Precompute
    t1 = time.perf_counter()
    print("Precomputing indicators...")
    pre = precompute(df)
    print(f"  done in {time.perf_counter()-t1:.1f}s")

    # BB caches
    t2 = time.perf_counter()
    bb_lo, bb_mid, bb_hi = build_bb_cache(pre["n"], pre["close"])
    print(f"BB cache: {time.perf_counter()-t2:.1f}s")

    # EMA caches
    t3 = time.perf_counter()
    ema_f_cache, ema_s_cache = build_ema_cache(pre["n"], pre["close"])
    print(f"EMA cache: {time.perf_counter()-t3:.1f}s")

    all_results: list[Result] = []

    if MODE in ("RANGE", "BOTH"):
        print("\n--- Scanning RANGE mode ---")
        r_results = scan_range(pre, bb_lo, bb_mid, bb_hi)
        all_results.extend(r_results)
        report(r_results, "RANGE")

    if MODE in ("TREND", "BOTH"):
        print("\n--- Scanning TREND mode ---")
        t_results = scan_trend(pre, ema_f_cache, ema_s_cache)
        all_results.extend(t_results)
        report(t_results, "TREND")

    # Save
    out = [
        {
            "mode": r.mode,
            "params": {"p1": r.p1, "p2": r.p2, "p3": r.p3, "p4": r.p4, "p5": r.p5, "p6": r.p6},
            "total_return": round(r.total_return, 2),
            "ann_return": round(r.ann_return, 2),
            "num_trades": r.num_trades,
            "win_rate": round(r.win_rate, 4),
            "avg_win": round(r.avg_win, 4),
            "avg_loss": round(r.avg_loss, 4),
            "profit_factor": round(r.profit_factor, 4),
            "max_dd": round(r.max_dd, 2),
            "sharpe": round(r.sharpe, 4),
            "score": round(r.score, 4),
            "longs": r.longs,
            "shorts": r.shorts,
            "avg_bars": round(r.avg_bars, 2),
        }
        for r in all_results
    ]
    Path("scripts/dual_mode_results.json").write_text(json.dumps(out, indent=2))

    print(f"\nTotal time: {time.perf_counter()-t0:.1f}s")
    print(f"Saved {len(out)} results to scripts/dual_mode_results.json")


if __name__ == "__main__":
    main()
