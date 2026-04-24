#!/usr/bin/env python3
"""Cross-symbol verification: does EMA(15,50) + BB strategy work on EURUSD/GBPUSD?"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.scan_short_term import (
    precompute_base, build_bb_cache, build_ema_cache,
    build_pat_cache, backtest_combo, make_result,
    BB_PERIODS, BB_STDS, EMA_FASTS, EMA_SLOWS,
)

def verify_symbol(symbol: str, bb_p: int, bb_s: float,
                  ef: int, es: int, sl: float, tp: float, mb: int):
    fname = symbol.lower().replace('/', '')
    data_path = Path(__file__).parent.parent / "backtest_data" / "candles" / f"{fname}_1h.parquet"
    if not data_path.exists():
        print(f"{symbol}: no 1h data")
        return
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    n = len(df)
    years = n / (24 * 365)
    print(f"\n{symbol}: {n} bars ({years:.1f} yrs) {df['timestamp'].iloc[0].date()} to {df['timestamp'].iloc[-1].date()}")

    pre = precompute_base(df)
    bb_cache = build_bb_cache(n, pre["close"])
    ef_cache, es_cache = build_ema_cache(n, pre["close"])
    pat_cache = build_pat_cache(n, df, pre["close"])

    bpi = BB_PERIODS.index(bb_p)
    bsi = BB_STDS.index(bb_s)
    efi = EMA_FASTS.index(ef)
    esi = EMA_SLOWS.index(es)

    ret, n_t, wr, aw, al, pf, dd, exp = backtest_combo(
        sl, tp, mb, pre,
        bb_cache[bpi, bsi],
        ef_cache[efi, esi],
        es_cache[efi, esi],
        pat_cache[bpi, bsi],
    )
    r = make_result(bb_p, bb_s, ef, es, sl, tp, mb, ret, n_t, wr, aw, al, pf, dd, exp)
    annual = r.total_return / years if years > 0 else 0
    print(f"  BB({bb_p},{bb_s}) EMA({ef},{es}) SL{sl} TP{tp} MB{mb}")
    print(f"  Ret={r.total_return:+.2f}% ({annual:+.2f}%/yr) N={r.num_trades} "
          f"WR={r.win_rate:.1%} PF={r.profit_factor:.2f} DD={r.max_dd:.1f}% Score={r.score:.3f}")

print("=== Optimal config: BB(8,2.0) EMA(15,50) SL2.3 TP3.0 MB3 ===")
for symbol in ["XAUUSD", "EURUSD", "GBPUSD"]:
    verify_symbol(symbol, bb_p=8, bb_s=2.0, ef=15, es=50, sl=2.3, tp=3.0, mb=3)
