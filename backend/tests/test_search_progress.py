from app.services.search_progress import entry_family_label


def test_entry_family_label_maps_types():
    spec = {"entry": {"type": "opening_range_breakout"}, "category": "opening_range_breakout"}
    assert entry_family_label(spec) == "ORB"


def test_entry_family_label_reverse():
    spec = {"category": "reversed_rsi_reversion", "entry": {"type": "rsi_reversion"}}
    assert entry_family_label(spec) == "Fade RSI"