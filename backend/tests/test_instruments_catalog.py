from app.services.instruments import CURATED_SYMBOLS, INSTRUMENT_SPECS


def test_curated_count_and_symbols():
    assert len(INSTRUMENT_SPECS) == 7
    assert CURATED_SYMBOLS == frozenset({"ES", "MES", "NQ", "MNQ", "CL", "GC", "MGC"})