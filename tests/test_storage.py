"""Plain-assert tests for the storage abstraction (no pytest dependency).

Run: python tests/test_storage.py

The S3 path itself is exercised end-to-end in CI against a real MinIO
container (tests/test_remote_storage.py). Here we prove the abstraction:
the same bronze code must behave identically on local disk and on a
non-local fsspec backend (memory://), which is what makes s3:// a
configuration change instead of a code change.
"""

import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from ingest.ingest import add_provenance, count_bronze_rows, validate, write_bronze
from ingest.storage import Storage

PASSED = 0


def check(name, fn):
    global PASSED
    fn()
    PASSED += 1
    print(f"ok - {name}")


def good_df():
    return pd.DataFrame(
        {
            "date": ["2024-01-01", "2025-02-01"],
            "item_code": ["CP00", "CP00"],
            "item_name": ["All items", "All items"],
            "index_value": [100.0, 105.0],
        }
    )


def prepared(df=None, fetched_at="2026-08-21T10:00:00+00:00"):
    return add_provenance(validate(df if df is not None else good_df()), "test", fetched_at)


def mem_uri():
    """Unique memory:// prefix per test (MemoryFileSystem is process-global)."""
    return f"memory://{uuid.uuid4().hex}/bronze"


def test_local_uri_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = Storage.from_uri(tmp)
        assert store.is_local
        p = store.join("cpi", "year=2024", "data.parquet")
        store.write_parquet(good_df(), p)
        back = store.read_parquet(p)
        assert len(back) == 2
        assert store.glob("cpi/year=*/data.parquet") == [p]


def test_memory_uri_roundtrip():
    store = Storage.from_uri(mem_uri())
    assert not store.is_local
    p = store.join("cpi", "year=2024", "data.parquet")
    store.write_parquet(good_df(), p)
    assert len(store.read_parquet(p)) == 2
    assert len(store.glob("cpi/year=*/data.parquet")) == 1


def test_write_bronze_on_memory_backend():
    uri = mem_uri()
    written = write_bronze(prepared(), uri)
    assert len(written) == 2, f"expected 2 partitions, got {len(written)}"
    assert all(isinstance(p, str) for p in written)
    assert count_bronze_rows(uri) == 2


def test_reingest_memory_idempotent():
    uri = mem_uri()
    write_bronze(prepared(), uri)
    n1 = count_bronze_rows(uri)
    write_bronze(prepared(fetched_at="2026-08-21T11:00:00+00:00"), uri)
    n2 = count_bronze_rows(uri)
    assert n1 == n2 == 2, f"idempotency broken on memory backend: {n1} -> {n2}"


def test_revision_memory_incoming_wins():
    uri = mem_uri()
    write_bronze(prepared(), uri)
    revised = good_df()
    revised.loc[0, "index_value"] = 999.0
    write_bronze(prepared(revised, fetched_at="2026-08-21T11:00:00+00:00"), uri)
    store = Storage.from_uri(uri)
    out = store.read_parquet(store.join("cpi", "year=2024", "data.parquet"))
    assert out["index_value"].iloc[0] == 999.0, "incoming row must win on collision"
    assert count_bronze_rows(uri) == 2


def test_s3_endpoint_env_is_wired():
    """s3:// must pick up LAKE_S3_ENDPOINT (skipped when s3fs not installed)."""
    try:
        import s3fs  # noqa: F401
    except ImportError:
        print("skip - test_s3_endpoint_env_is_wired (s3fs not installed)")
        return
    import os

    os.environ["LAKE_S3_ENDPOINT"] = "http://localhost:9000"
    try:
        store = Storage.from_uri("s3://lake/bronze")
        assert not store.is_local
        assert store.base == "lake/bronze"
        assert store.fs.client_kwargs.get("endpoint_url") == "http://localhost:9000"
    finally:
        del os.environ["LAKE_S3_ENDPOINT"]


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
