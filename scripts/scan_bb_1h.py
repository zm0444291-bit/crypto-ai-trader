"""
BB策略1h参数扫描 — XAUUSD 2025全年
用固定分数风险管理：每笔风险账户的1%作为止损单位
"""
import pandas as pd
import numpy as np

def backtest_bb_1h(df: pd.DataFrame, bb_period: int, bb_std: float,
                   stop_atr: float = 1.5, profit_atr: float = 2.0,
                   risk_pct: float = 0.01,
                   use_sma_filter: bool = False,
                   sma_fast: int = 10, sma_slow: int = 30,
                   max_hours: int = 48) -> dict:
    """
    BB策略回测，1h数据，固定分数风险管理
    每笔交易风险账户的risk_pct%，用ATR设置止损距离
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    n = len(df)

    # BB计算
    mid = pd.Series(close).rolling(bb_period).mean().values
    std = pd.Series(close).rolling(bb_period).std().values
    upper = mid + bb_std * std
    lower = mid - bb_std * std

    # ATR (14周期)
    tr = np.maximum(high - low, np.maximum(abs(high - np.roll(close, 1)), abs(low - np.roll(close, 1))))
    atr = pd.Series(tr).rolling(14).mean()
    atr = atr.fillna(atr.iloc[14]).values

    # SMA filter
    if use_sma_filter:
        sma_f = pd.Series(close).rolling(sma_fast).mean().values
        sma_s = pd.Series(close).rolling(sma_slow).mean().values

    trades = []
    equity = 1.0
    position = 0.0
    entry_price = 0.0
    entry_atr = 0.0
    entry_idx = 0

    for i in range(bb_period + 2, n - 1):
        if position == 0:
            if use_sma_filter:
                if not (sma_f[i] > sma_s[i] and close[i] > sma_f[i]):
                    continue

            # 入场：下轨触价
            if low[i] <= lower[i] < close[i]:
                position = 1
                entry_price = max(lower[i], close[i])
                entry_atr = max(atr[i], 1.0)  # 防止ATR=0
                entry_idx = i

        elif position == 1:
            # 止损
            sl_price = entry_price - stop_atr * entry_atr
            if low[i] <= sl_price:
                # 止损触发，计算R倍数
                r = -risk_pct  # 固定亏损
                trades.append(r)
                equity *= (1 + r)
                position = 0
                continue

            # 止盈
            tp_price = entry_price + profit_atr * entry_atr
            if high[i] >= tp_price:
                r = risk_pct * (profit_atr / stop_atr)  # R倍数
                trades.append(r)
                equity *= (1 + r)
                position = 0
                continue

            # 时间止损
            if i - entry_idx > max_hours:
                # 按当时盈亏平仓
                ret = (close[i] - entry_price) / entry_price
                r = ret / (stop_atr * entry_atr / entry_price) * risk_pct
                r = max(-risk_pct, min(r, risk_pct * 3))  # 限制在±3R
                trades.append(r)
                equity *= (1 + r)
                position = 0
                continue

    if position == 1:
        ret = (close[-1] - entry_price) / entry_price
        r = ret / (stop_atr * entry_atr / entry_price) * risk_pct
        r = max(-risk_pct, min(r, risk_pct * 3))
        trades.append(r)
        equity *= (1 + r)

    if not trades:
        return {
            'total_return': 0.0,
            'n_trades': 0,
            'win_rate': 0.0,
            'avg_R': 0.0,
            'max_dd': 0.0,
            'equity': 1.0,
        }

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]

    # 最大回撤
    peak = 1.0
    max_dd = 0.0
    eq = 1.0
    for t in trades:
        eq *= (1 + t)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd

    return {
        'total_return': (equity - 1.0) * 100,
        'n_trades': len(trades),
        'win_rate': len(wins) / len(trades) * 100,
        'avg_R': np.mean(trades) / risk_pct if trades else 0,
        'avg_R_win': np.mean(wins) / risk_pct if wins else 0,
        'avg_R_loss': np.mean(losses) / risk_pct if losses else 0,
        'max_dd': max_dd * 100,
        'equity': equity,
    }


def main():
    df = pd.read_parquet('backtest_data/candles/xauusd_1h.parquet')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    df = df.set_index('timestamp')

    print(f"Data: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")
    print(f"Risk per trade: 1% of equity (fixed fractional)")
    print()

    # 扫描
    results = []
    bb_periods = [5, 7, 10, 14, 20]
    bb_stds = [0.5, 1.0, 1.5, 2.0, 2.5]
    stop_atrs = [1.0, 1.5, 2.0]
    profit_atrs = [1.5, 2.0, 2.5, 3.0]

    for bb_p in bb_periods:
        for bb_s in bb_stds:
            for stop_atr in stop_atrs:
                for profit_atr in profit_atrs:
                    r = backtest_bb_1h(df, bb_p, bb_s, stop_atr, profit_atr,
                                       risk_pct=0.01, use_sma_filter=False,
                                       max_hours=48)
                    r.update({
                        'bb_period': bb_p,
                        'bb_std': bb_s,
                        'stop_atr': stop_atr,
                        'profit_atr': profit_atr,
                        'rr': profit_atr / stop_atr,
                    })
                    results.append(r)

    results.sort(key=lambda x: x['total_return'], reverse=True)

    print(f"{'BB(p,s)':>10} {'Stop':>5} {'RR':>4} {'Return%':>8} {'Trades':>6} {'Win%':>6} {'AvgR':>6} {'MaxDD':>7}")
    print("-" * 65)
    for r in results[:30]:
        print(f"BB({r['bb_period']},{r['bb_std']}) {r['stop_atr']:>5.1f} {r['rr']:>4.1f} "
              f"{r['total_return']:>8.1f}% {r['n_trades']:>6} {r['win_rate']:>6.1f}% "
              f"{r['avg_R']:>6.2f} {r['max_dd']:>7.1f}%")

    # SMA版本
    print()
    print("=== SMA Filter 版本 ===")
    results2 = []
    for bb_p in [5, 7, 10, 14]:
        for bb_s in [0.5, 1.0, 1.5, 2.0]:
            for sma_f, sma_s in [(10, 30), (20, 60), (10, 60)]:
                for stop_atr in [1.0, 1.5, 2.0]:
                    r = backtest_bb_1h(df, bb_p, bb_s, stop_atr, profit_atr=stop_atr * 1.5,
                                       risk_pct=0.01, use_sma_filter=True,
                                       sma_fast=sma_f, sma_slow=sma_s,
                                       max_hours=48)
                    r.update({
                        'bb_period': bb_p,
                        'bb_std': bb_s,
                        'sma_f': sma_f,
                        'sma_s': sma_s,
                        'stop_atr': stop_atr,
                    })
                    results2.append(r)

    results2.sort(key=lambda x: x['total_return'], reverse=True)

    print(f"{'BB(p,s)':>10} {'SMA':>10} {'Stop':>5} {'Return%':>8} {'Trades':>6} {'Win%':>6} {'AvgR':>6} {'MaxDD':>7}")
    print("-" * 75)
    for r in results2[:20]:
        print(f"BB({r['bb_period']},{r['bb_std']}) SMA({r['sma_f']},{r['sma_s']}) {r['stop_atr']:>5.1f} "
              f"{r['total_return']:>8.1f}% {r['n_trades']:>6} {r['win_rate']:>6.1f}% "
              f"{r['avg_R']:>6.2f} {r['max_dd']:>7.1f}%")


if __name__ == '__main__':
    main()
