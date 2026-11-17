import hashlib
import json

from app.backtest import ENGINE_VERSION


def build_reproducibility_id(
    *,
    strategy_version_id: str,
    dataset_id: str,
    dataset_version: str,
    bar_count: int,
    assumptions: dict,
    parameters: dict,
) -> str:
    payload = {
        "engine_version": ENGINE_VERSION,
        "strategy_version_id": strategy_version_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "bar_count": bar_count,
        "assumptions": assumptions,
        "parameters": parameters,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:32]