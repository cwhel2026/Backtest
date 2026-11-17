from decimal import Decimal

import pytest

from app.models.enums import AssetClass
from app.models.instrument import Instrument
from app.services.futures_math import commission_round_trip, contracts_for_risk, risk_dollars


def _mes() -> Instrument:
    return Instrument(
        symbol="MES",
        name="Micro E-mini S&P 500",
        asset_class=AssetClass.EQUITY_INDEX,
        tick_size=Decimal("0.25"),
        tick_value=Decimal("1.25"),
        multiplier=Decimal("5"),
        trading_hours={},
        default_commission_per_side=Decimal("0.62"),
    )


def test_risk_dollars_mes():
    inst = _mes()
    # 4 ticks = 1 point move = $5 per MES contract
    assert risk_dollars(Decimal("1.0"), inst) == Decimal("5.00")


def test_contracts_for_risk():
    inst = _mes()
    qty = contracts_for_risk(Decimal("5000"), Decimal("4999"), Decimal("100"), inst)
    assert qty == 20


def test_commission_round_trip():
    inst = _mes()
    assert commission_round_trip(inst) == Decimal("1.24")