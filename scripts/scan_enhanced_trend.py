#!/usr/bin/env python3
"""
scan_enhanced_trend.py — 增强趋势策略扫描 (预计算版)
预计算所有 EMA 组合，回测时 O(1) 查找。
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

EMA_FAST_LIST   = [5, 8, 10, 12, 15]
EMA_SLOW_LIST   = [20, 30, 50]
ADX_LIST        = [15, 18, 20, 22, 25]
SL_ATR_LIST     = [1.5, 2.0, 2.5, 3.0]
TP_ATR_LIST     = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
MAX_BARS_LIST   = [4, 5, 6, 8, 10]
RSI_CONF_LIST   = [True, False]
VOL_CONF_LIST   = [True, False]


@dataclass
class Result:
    mode: str
    ef: int; es: int; adx_th: float; sl: float; tp: float; mb: int
    rsi_conf: bool; vol_conf: bool
    total_return: float; ann_return: float; num_trades: int
    win_rate: float; avg_win: float; avg_loss: float; profit_factor: float
    max_dd: float; sharpe: float; score: float
    longs: int; shorts: int; avg_bars: float


def load_data() -> pd.DataFrame:
    data_path = Path(__file__).parent.parent / "backtest_data" / "candles" / "xauusd_1h.parquet"
    df = pq.read_table(data_path).to_pandas()
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def prepare(df: pd.DataFrame) -> tuple[dict, dict]:
    c = df["close"].astype(float).values
    h = df["high"].astype(float).values
    lo = df["low"].astype(float).values
    v  = df["volume"].astype(float).values
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

    dx = np.full(n, np.nan)
    ema_up = ema_dn = 0.0
    for i in range(1, n):
        up = h[i] - h[i-1]
        dn = lo[i-1] - lo[i]
        dm_plus = up if up > dn and up > 0 else 0.0
        dm_minus = dn if dn > up and dn > 0 else 0.0
        ema_up  = ema_up  + alpha * (dm_plus - ema_up)
        ema_dn  = ema_dn  + alpha * (dm_minus - ema_dn)
        denom = ema_up + ema_dn
        dx[i] = 0.0 if denom == 0 else 100 * abs(ema_up - ema_dn) / denom

    adx = np.full(n, np.nan)
    adx_s = 0.0
    for i in range(1, n):
        adx_s = adx_s + alpha * (dx[i] - adx_s)
        adx[i] = adx_s

    rsi = np.full(n, np.nan)
    avg_gain = avg_loss = 0.0
    for i in range(1, n):
        gain = max(c[i] - c[i-1], 0.0)
        loss = max(c[i-1] - c[i], 0.0)
        if i <= 14:
            avg_gain += gain
            avg_loss += loss
            if i == 14:
                avg_gain /= 14; avg_loss /= 14
                rs = avg_gain / (avg_loss + 1e-12)
                rsi[i] = 100 - 100 / (1 + rs)
        else:
            avg_gain = avg_gain + alpha * (gain - avg_gain)
            avg_loss = avg_loss + alpha * (loss - avg_loss)
            rs = avg_gain / (avg_loss + 1e-12)
            rsi[i] = 100 - 100 / (1 + rs)

    vol_sma = pd.Series(v).rolling(20, min_periods=1).mean().values

    ts = pd.to_datetime(df["timestamp"], utc=True)
    hour_utc = ts.dt.hour + ts.dt.minute / 60.0
    session_ok = np.array([h_ >= 13.5 and h_ <= 21.0 or h_ <= 3.0 for h_ in hour_utc])

    pre = {
        "close": c, "high": h, "low": lo, "volume": v,
        "atr": atr, "adx": adx, "rsi": rsi,
        "vol_sma": vol_sma, "session_ok": session_ok, "n": n,
    }

    # Precompute all EMA arrays
    all_periods = sorted(set(EMA_FAST_LIST + EMA_SLOW_LIST))
    ema_arrays = {}
    for p in all_periods:
        ema_arrays[p] = compute_ema_vectorized(c, p)

    return pre, ema_arrays


def compute_ema_vectorized(c: np.ndarray, period: int) -> np.ndarray:
    """Wilder EMA (span = 2*period - 1 equivalent)."""
    n = len(c)
    out = np.zeros(n, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    s = float(c[0])
    out[0] = s
    for i in range(1, n):
        s = s + alpha * (c[i] - s)
        out[i] = s
    return out


def bt_enhanced(
    pre: dict,
    ef: int, es: int, adx_th: float,
    sl: float, tp: float, max_bars: int,
    rsi_conf: bool, vol_conf: bool,
    ema_arrays: dict[int, np.ndarray],
) -> tuple:
    c = pre["close"]; lo = pre["low"]; h = pre["high"]
    atr = pre["atr"]; adx = pre["adx"]; rsi = pre["rsi"]
    v = pre["volume"]; vol_sma = pre["vol_sma"]
    session_ok = pre["session_ok"]
    n = pre["n"]

    ef_arr = ema_arrays[ef]
    es_arr = ema_arrays[es]

    eq = INITIAL_EQUITY; peak = eq; max_dd = 0.0
    pnl_list: list[float] = []
    bars_list: list[int] = []
    longs = 0; shorts = 0
    pos = 0; entry_p = 0.0; sl_p = 0.0; tp_p = 0.0; entry_bar = 0

    for i in range(WARMUP, n):
        c_i = c[i]; lo_i = lo[i]; hi_i = h[i]
        adx_i = adx[i]; rsi_i = rsi[i]
        v_i = v[i]; vol_sma_i = vol_sma[i]

        if pos == 0:
            if not session_ok[i]:
                continue

            ef_i = ef_arr[i]; es_i = es_arr[i]
            ef_prev = ef_arr[i-1]; es_prev = es_arr[i-1]
            bull_cross = ef_prev <= es_prev and ef_i > es_i
            bear_cross = ef_prev >= es_prev and ef_i < es_i

            if not bull_cross and not bear_cross:
                continue

            if vol_conf and vol_sma_i > 0 and v_i < 1.5 * vol_sma_i:
                continue

            if rsi_conf:
                if bull_cross and (np.isnan(rsi_i) or rsi_i <= 50):
                    continue
                if bear_cross and (np.isnan(rsi_i) or rsi_i >= 50):
                    continue

            if adx_i < adx_th:
                continue

            if bull_cross:
                pos = 1; entry_p = c_i
                sl_p = c_i - sl * atr[i]
                tp_p = c_i + tp * atr[i]
                entry_bar = i; longs += 1
            elif bear_cross:
                pos = -1; entry_p = c_i
                sl_p = c_i + sl * atr[i]
                tp_p = c_i - tp * atr[i]
                entry_bar = i; shorts += 1

        elif pos == 1:
            bars = i - entry_bar
            ef_i = ef_arr[i]; es_i = es_arr[i]
            ef_prev = ef_arr[i-1]; es_prev = es_arr[i-1]
            dead_cross = ef_prev >= es_prev and ef_i < es_i

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
            elif dead_cross or bars >= max_bars:
                pct = (c_i - entry_p) / entry_p * 100
                pnl_list.append(pct); bars_list.append(bars)
                eq *= (1 + pct/100); peak = max(peak, eq)
                max_dd = max(max_dd, (peak - eq) / peak); pos = 0

        elif pos == -1:
            bars = i - entry_bar
            ef_i = ef_arr[i]; es_i = es_arr[i]
            ef_prev = ef_arr[i-1]; es_prev = es_arr[i-1]
            gold_cross = ef_prev <= es_prev and ef_i > es_i

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
            elif gold_cross or bars >= max_bars:
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
    print(f"  {len(df)} bars")

    print("Preparing indicators (includes EMA precompute)...")
    t0 = time.time()
    pre, ema_arrays = prepare(df)
    print(f"  Done in {time.time()-t0:.1f}s")

    total = sum(
        1 for ef in EMA_FAST_LIST
          for es in EMA_SLOW_LIST
          if es > ef
          for _adx in ADX_LIST
          for sl in SL_ATR_LIST
          for tp in TP_ATR_LIST
          if tp > sl
          for _mb in MAX_BARS_LIST
          for _rsi in RSI_CONF_LIST
          for _vol in VOL_CONF_LIST
    )
    print(f"Scanning {total} combos...")

    results: list[Result] = []
    done = 0
    t0 = time.time()

    for ef in EMA_FAST_LIST:
        for es in EMA_SLOW_LIST:
            if es <= ef:
                continue
            for adx_th in ADX_LIST:
                for sl in SL_ATR_LIST:
                    for tp in TP_ATR_LIST:
                        if tp <= sl:
                            continue
                        for mb in MAX_BARS_LIST:
                            for rsi_conf in RSI_CONF_LIST:
                                for vol_conf in VOL_CONF_LIST:
                                    ret, ann, n_t, wr, aw, al, pf, longs, shorts, avg_b, sh, dd, sc = bt_enhanced(
                                        pre, ef, es, adx_th, sl, tp, mb,
                                        rsi_conf, vol_conf, ema_arrays,
                                    )
                                    results.append(Result(
                                        mode="ENHANCED_TREND",
                                        ef=ef, es=es, adx_th=adx_th,
                                        sl=sl, tp=tp, mb=mb,
                                        rsi_conf=rsi_conf, vol_conf=vol_conf,
                                        total_return=ret, ann_return=ann,
                                        num_trades=n_t, win_rate=wr,
                                        avg_win=aw, avg_loss=al, profit_factor=pf,
                                        max_dd=dd, sharpe=sh, score=sc,
                                        longs=longs, shorts=shorts, avg_bars=avg_b,
                                    ))
                                    done += 1
                                    if done % 2000 == 0:
                                        elapsed = time.time() - t0
                                        rate = done / elapsed
                                        eta = (total - done) / rate
                                        print(f"  {done}/{total} ({done/total*100:.1f}%) — ETA {eta:.0f}s")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s — {done} combos")

    results.sort(key=lambda r: r.score, reverse=True)
    print("\n=== TOP 10 ENHANCED TREND ===")
    for i, x in enumerate(results[:10]):
        print(f"\n{i+1}. Score={x.score:.3f} PF={x.profit_factor:.2f} WR={x.win_rate:.1%} "
              f"Trades={x.num_trades} Ann={x.ann_return:.1%} DD={x.max_dd:.1%}")
        print(f"   EF={x.ef} ES={x.es} ADX>={x.adx_th} SL={x.sl} TP={x.tp} MB={x.mb} "
              f"RSI_conf={x.rsi_conf} Vol_conf={x.vol_conf}")
        print(f"   Longs={x.longs} Shorts={x.shorts} AvgBars={x.avg_bars:.1f}")

    out_path = Path(__file__).parent / "enhanced_trend_results.json"
    with open(out_path, "w") as f:
        json.dump([{
            "mode": r.mode,
            "params": {"ef": r.ef, "es": r.es, "adx_th": r.adx_th, "sl": r.sl,
                       "tp": r.tp, "mb": r.mb, "rsi_conf": r.rsi_conf, "vol_conf": r.vol_conf},
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
