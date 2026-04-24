from decimal import Decimal


def ema(values: list[Decimal], period: int) -> list[Decimal | None]:
    """Exponential moving average.

    Returns a list of the same length as input. Values are None until
    enough data accumulates (period - 1 warmup steps).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    n = len(values)
    result: list[Decimal | None] = [None] * n

    if n == 0 or period == 0:
        return result

    multiplier = Decimal(2) / Decimal(period + 1)

    # Seed: SMA over first 'period' values
    if n < period:
        return result

    # seed with simple average of first period values
    seed = sum(values[:period]) / Decimal(period)
    result[period - 1] = seed

    for i in range(period, n):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]  # type: ignore[operator]

    return result


def rsi(values: list[Decimal], period: int = 14) -> list[Decimal | None]:
    """Relative Strength Index.

    Returns a list of the same length as input. Values are None until
    enough data exists to compute the first RSI (2 * period steps).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    n = len(values)
    result: list[Decimal | None] = [None] * n

    if n < period + 1:
        return result

    gains: list[Decimal] = []
    losses: list[Decimal] = []

    for i in range(1, n):
        change = values[i] - values[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(Decimal(0))
        else:
            gains.append(Decimal(0))
            losses.append(-change)

    if len(gains) < period:
        return result

    # First RSI: use SMA for initial averages
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    first_rsi_idx = period
    if avg_loss == 0:
        result[first_rsi_idx] = Decimal(100)
    else:
        rs = avg_gain / avg_loss
        result[first_rsi_idx] = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))

    # Subsequent RSI: smoothed using Wilder's method
    for i in range(period + 1, n):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i - 1]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i - 1]) / Decimal(period)

        if avg_loss == 0:
            result[i] = Decimal(100)
        else:
            rs = avg_gain / avg_loss
            result[i] = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))

    return result


def true_range(high: Decimal, low: Decimal, previous_close: Decimal | None) -> Decimal:
    """True range for a single candle.

    Handles the case where previous_close is None (first candle).
    """
    if previous_close is None:
        return high - low

    high_to_prev_close = abs(high - previous_close)
    low_to_prev_close = abs(low - previous_close)

    return max(high - low, high_to_prev_close, low_to_prev_close)


def atr(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    """Average True Range.

    Returns a list of the same length as input. Values are None until
    enough data exists (period warmup steps).
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")

    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError(
            f"highs, lows, and closes must have the same length: "
            f"got {len(highs)}, {len(lows)}, {len(closes)}"
        )

    n = len(highs)
    result: list[Decimal | None] = [None] * n

    if n < period:
        return result

    # Compute true range for each candle
    tr_list: list[Decimal] = []
    for i in range(n):
        prev_close = closes[i - 1] if i > 0 else None
        tr_list.append(true_range(highs[i], lows[i], prev_close))

    # First ATR: simple average of first 'period' true ranges
    result[period - 1] = sum(tr_list[:period]) / Decimal(period)

    # Subsequent ATRs: smoothed
    for i in range(period, n):
        result[i] = (result[i - 1] * Decimal(period - 1) + tr_list[i]) / Decimal(period)  # type: ignore[operator]

    return result
