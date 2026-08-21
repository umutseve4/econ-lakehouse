"""CI end-to-end test: the bronze lake on S3-compatible object storage (MinIO).

Requires a running S3 endpoint and these environment variables:
    LAKE_S3_ENDPOINT       e.g. http://localhost:9000
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY

Proves that the EXACT SAME ingest code (write_bronze / count_bronze_rows)
works against object storage: partitioned write, idempotent re-ingest, and
incoming-wins revision — with zero code changes, only a URI change.

Prints an OTOMATIK KONTROL block; exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from ingest.ingest import add_provenance, count_bronze_rows, validate, write_bronze
from ingest.storage import Storage

BUCKET = "lake"
BRONZE_URI = f"s3://{BUCKET}/bronze"
FIXTURE = ROOT / "data" / "sample" / "cpi_fixture.csv"


def wait_for_s3(store: Storage, timeout: int = 90) -> bool:
    """MinIO may still be booting when the job starts — retry, don't flake."""
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            store.fs.invalidate_cache()
            store.fs.ls("")
            return True
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(3)
    print(f"endpoint unreachable after {timeout}s: {last}")
    return False


def prepared(df: pd.DataFrame, fetched_at: str) -> pd.DataFrame:
    return add_provenance(validate(df), "fixture:synthetic", fetched_at)


def main() -> int:
    checks: list[tuple[str, str]] = []
    status = 0
    try:
        store = Storage.from_uri(BRONZE_URI)
        assert wait_for_s3(store), "S3 endpoint not reachable"
        checks.append(("s3_endpoint_reachable", "PASS"))

        if not store.fs.exists(BUCKET):
            store.fs.mkdir(BUCKET)
        checks.append(("bucket_ready", f"PASS ({BUCKET})"))

        base = pd.read_csv(FIXTURE)

        # 1) Partitioned write to S3.
        written = write_bronze(prepared(base, "2026-08-21T10:00:00+00:00"), BRONZE_URI)
        n1 = count_bronze_rows(BRONZE_URI)
        ok = len(written) > 0 and n1 == len(base)
        checks.append(
            ("s3_partitioned_write",
             f"{'PASS' if ok else 'FAIL'} ({len(written)} partitions, {n1} rows)")
        )
        assert ok

        # 2) Idempotent re-ingest.
        write_bronze(prepared(base, "2026-08-21T11:00:00+00:00"), BRONZE_URI)
        n2 = count_bronze_rows(BRONZE_URI)
        checks.append(
            ("s3_idempotent_reingest",
             f"{'PASS' if n1 == n2 else 'FAIL'} ({n1} -> {n2})")
        )
        assert n1 == n2

        # 3) Revision: incoming wins, row count unchanged.
        rev = base.iloc[[0]].copy()
        revised_val = round(float(rev["index_value"].iloc[0]) * 1.01, 4)
        rev["index_value"] = revised_val
        write_bronze(prepared(rev, "2026-08-21T12:00:00+00:00"), BRONZE_URI)
        n3 = count_bronze_rows(BRONZE_URI)

        key_date = pd.to_datetime(rev["date"].iloc[0])
        year = key_date.year
        out = store.read_parquet(store.join("cpi", f"year={year}", "data.parquet"))
        out["date"] = pd.to_datetime(out["date"])
        row = out[(out["date"] == key_date) & (out["item_code"] == rev["item_code"].iloc[0])]
        got = float(row["index_value"].iloc[0])
        ok = n3 == n1 and abs(got - revised_val) < 1e-9
        checks.append(
            ("s3_revision_incoming_wins",
             f"{'PASS' if ok else 'FAIL'} (rows={n3}, value={got})")
        )
        assert ok
    except Exception as exc:  # noqa: BLE001
        checks.append(("remote_storage_test", f"FAIL — {exc}"))
        status = 1

    print("===== OTOMATIK KONTROL =====")
    for name, result in checks:
        print(f"{name}: {result}")
    print(f"RESULT: {'PASS' if status == 0 else 'FAIL'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
