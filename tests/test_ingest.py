"""Plain-assert tests for the bronze ingest layer (no pytest dependency).

Run: python tests/test_ingest.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from ingest.ingest import ValidationError, validate, write_bronze

PASSED = 0


def check(name, fn):
    global PASSED
    fn()
    PASSED += 1
    print(f"ok - {name}")


def good_df():
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-02-01"],
            "item_code": ["CP00", "CP00"],
            "item_name": ["All items", "All items"],
            "index_value": [100.0, 105.0],
        }
    )


def test_valid_passes():
    df = validate(good_df())
    assert len(df) == 2
    assert str(df["date"].dtype).startswith("datetime64")


def test_missing_column_fails():
    df = good_df().drop(columns=["index_value"])
    try:
        validate(df)
    except ValidationError as e:
        assert "missing columns" in str(e)
    else:
        raise AssertionError("expected ValidationError")


def test_negative_value_fails():
    df = good_df()
    df.loc[0, "index_value"] = -5
    try:
        validate(df)
    except ValidationError as e:
        assert "must be > 0" in str(e)
    else:
        raise AssertionError("expected ValidationError")


def test_duplicate_fails():
    df = pd.concat([good_df(), good_df().iloc[[0]]], ignore_index=True)
    try:
        validate(df)
    except ValidationError as e:
        assert "duplicate" in str(e)
    else:
        raise AssertionError("expected ValidationError")


def test_bad_date_fails():
    df = good_df()
    df.loc[0, "date"] = "not-a-date"
    try:
        validate(df)
    except ValidationError as e:
        assert "unparseable dates" in str(e)
    else:
        raise AssertionError("expected ValidationError")


def test_partitioned_write():
    df = good_df()
    df.loc[1, "date"] = "2025-02-01"
    df = validate(df)
    with tempfile.TemporaryDirectory() as tmp:
        written = write_bronze(df, Path(tmp))
        assert len(written) == 2, f"expected 2 partitions, got {len(written)}"
        years = sorted(p.parent.name for p in written)
        assert years == ["year=2024", "year=2025"], years
        total = sum(len(pd.read_parquet(p)) for p in written)
        assert total == 2


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            check(name, fn)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL - {name}: {e}")
    print("===== OTOMATIK KONTROL =====")
    print(f"tests: {PASSED} passed, {failed} failed")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    sys.exit(1 if failed else 0)
