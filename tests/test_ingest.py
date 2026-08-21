"""Plain-assert tests for the bronze ingest layer (no pytest dependency).

Run: python tests/test_ingest.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from ingest.ingest import (
    ValidationError,
    add_provenance,
    count_bronze_rows,
    validate,
    write_bronze,
)

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


def prepared(df=None, source="test", fetched_at=None):
    """validate + add_provenance in one step for write tests."""
    return add_provenance(validate(df if df is not None else good_df()), source, fetched_at)


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
    df = prepared(df)
    with tempfile.TemporaryDirectory() as tmp:
        written = write_bronze(df, Path(tmp))
        assert len(written) == 2, f"expected 2 partitions, got {len(written)}"
        years = sorted(p.parent.name for p in written)
        assert years == ["year=2024", "year=2025"], years
        total = sum(len(pd.read_parquet(p)) for p in written)
        assert total == 2


# ---------- M3: provenance ----------

def test_provenance_columns_present():
    df = prepared(source="evds:TP.FG.J0", fetched_at="2026-08-21T10:00:00+00:00")
    assert (df["source_name"] == "evds:TP.FG.J0").all()
    assert (df["fetched_at"] == "2026-08-21T10:00:00+00:00").all()


def test_provenance_default_timestamp_is_utc_iso():
    df = prepared()
    ts = df["fetched_at"].iloc[0]
    parsed = pd.Timestamp(ts)
    assert parsed.tzinfo is not None, "fetched_at must be timezone-aware"
    assert str(parsed.tz) in ("UTC", "utc"), f"expected UTC, got {parsed.tz}"


def test_write_without_provenance_fails():
    df = validate(good_df())
    with tempfile.TemporaryDirectory() as tmp:
        try:
            write_bronze(df, Path(tmp))
        except ValidationError as e:
            assert "provenance" in str(e)
        else:
            raise AssertionError("expected ValidationError")


# ---------- M3: idempotent incremental append ----------

def test_reingest_same_data_no_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        write_bronze(prepared(fetched_at="2026-08-21T10:00:00+00:00"), Path(tmp))
        n1 = count_bronze_rows(Path(tmp))
        write_bronze(prepared(fetched_at="2026-08-21T11:00:00+00:00"), Path(tmp))
        n2 = count_bronze_rows(Path(tmp))
        assert n1 == n2 == 2, f"idempotency broken: {n1} -> {n2}"


def test_reingest_updated_value_wins():
    with tempfile.TemporaryDirectory() as tmp:
        write_bronze(prepared(fetched_at="2026-08-21T10:00:00+00:00"), Path(tmp))
        revised = good_df()
        revised.loc[0, "index_value"] = 999.0  # revised observation
        write_bronze(prepared(revised, fetched_at="2026-08-21T11:00:00+00:00"), Path(tmp))
        out = pd.read_parquet(Path(tmp) / "cpi" / "year=2024" / "data.parquet")
        assert len(out) == 2, f"expected 2 rows, got {len(out)}"
        jan = out[out["date"] == pd.Timestamp("2024-01-01")]
        assert jan["index_value"].iloc[0] == 999.0, "incoming row must win on collision"
        assert jan["fetched_at"].iloc[0] == "2026-08-21T11:00:00+00:00"


def test_append_new_month_grows_partition():
    with tempfile.TemporaryDirectory() as tmp:
        write_bronze(prepared(), Path(tmp))
        extra = pd.DataFrame(
            {
                "date": ["2024-03-01"],
                "item_code": ["CP00"],
                "item_name": ["All items"],
                "index_value": [107.0],
            }
        )
        write_bronze(prepared(extra), Path(tmp))
        assert count_bronze_rows(Path(tmp)) == 3


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
