from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import AssetClass


class InstrumentOut(BaseModel):
    id: str
    symbol: str
    name: str
    asset_class: AssetClass
    exchange: str
    tick_size: Decimal
    tick_value: Decimal
    multiplier: Decimal
    is_micro: bool
    micro_of: str | None

    model_config = {"from_attributes": True}