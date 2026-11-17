from decimal import Decimal

from app.backtest.bars import Bar


def ema_series(values: list[Decimal], period: int) -> list[Decimal | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = Decimal(2) / Decimal(period + 1)
    seed = sum(values[:period]) / Decimal(period)
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (Decimal(1) - k)
        out[i] = prev
    return out


def rsi_series(values: list[Decimal], period: int = 14) -> list[Decimal | None]:
    """Wilder RSI. Index i uses closes through i (no lookahead)."""
    if period <= 0:
        raise ValueError("period must be positive")
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < period + 1:
        return out
    avg_gain = Decimal(0)
    avg_loss = Decimal(0)
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            avg_gain += delta
        else:
            avg_loss += -delta
    avg_gain /= Decimal(period)
    avg_loss /= Decimal(period)

    def _rsi(gain: Decimal, loss: Decimal) -> Decimal:
        if loss == 0:
            return Decimal(100)
        rs = gain / loss
        return Decimal(100) - (Decimal(100) / (Decimal(1) + rs))

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = delta if delta > 0 else Decimal(0)
        loss = -delta if delta < 0 else Decimal(0)
        avg_gain = (avg_gain * Decimal(period - 1) + gain) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + loss) / Decimal(period)
        out[i] = _rsi(avg_gain, avg_loss)
    return out


def bollinger_series(
    closes: list[Decimal],
    period: int = 20,
    std_mult: Decimal = Decimal("2"),
) -> tuple[list[Decimal | None], list[Decimal | None], list[Decimal | None]]:
    """Mid, upper, lower bands using population stdev of closes."""
    n = len(closes)
    mid: list[Decimal | None] = [None] * n
    upper: list[Decimal | None] = [None] * n
    lower: list[Decimal | None] = [None] * n
    if period <= 0 or n < period:
        return mid, upper, lower
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        m = sum(window) / Decimal(period)
        variance = sum((x - m) ** 2 for x in window) / Decimal(period)
        stdev = variance.sqrt() if variance > 0 else Decimal(0)
        mid[i] = m
        upper[i] = m + std_mult * stdev
        lower[i] = m - std_mult * stdev
    return mid, upper, lower


def atr_series(bars: list[Bar], period: int = 14) -> list[Decimal | None]:
    """Wilder ATR. Index i uses bars through i (no lookahead)."""
    out: list[Decimal | None] = [None] * len(bars)
    if period <= 0 or len(bars) < period:
        return out
    trs: list[Decimal] = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b.high - b.low)
            continue
        prev = bars[i - 1].close
        tr = max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
        trs.append(tr)
    atr = sum(trs[:period]) / Decimal(period)
    out[period - 1] = atr
    for i in range(period, len(bars)):
        atr = (atr * Decimal(period - 1) + trs[i]) / Decimal(period)
        out[i] = atr
    return out


def session_vwap(bars: list[Bar], session_date_key: list[str]) -> list[Decimal | None]:
    """session_date_key[i] groups bars into session buckets for VWAP."""
    out: list[Decimal | None] = [None] * len(bars)
    cum_pv: dict[str, Decimal] = {}
    cum_v: dict[str, Decimal] = {}
    for i, b in enumerate(bars):
        key = session_date_key[i]
        typical = (b.high + b.low + b.close) / Decimal(3)
        vol = Decimal(b.volume)
        cum_pv[key] = cum_pv.get(key, Decimal(0)) + typical * vol
        cum_v[key] = cum_v.get(key, Decimal(0)) + vol
        if cum_v[key] > 0:
            out[i] = cum_pv[key] / cum_v[key]
    return out