from app.util.serde import enum_value, normalize_created_by, provisional_reproducibility_id


def test_normalize_created_by_truncates_long_email():
    email = "verylonglocalpartname@my-long-domain.example.com"
    out = normalize_created_by(email)
    assert len(out) <= 32


def test_provisional_reproducibility_ids_unique():
    a = provisional_reproducibility_id()
    b = provisional_reproducibility_id()
    assert a != b
    assert len(a) <= 64


def test_normalize_created_by_keeps_short_labels():
    assert normalize_created_by("autopilot") == "autopilot"


def test_enum_value_accepts_str_or_enum():
    assert enum_value("running") == "running"

    class _E:
        value = "queued"

    assert enum_value(_E()) == "queued"