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