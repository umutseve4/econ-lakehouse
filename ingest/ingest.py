"""Bronze-layer ingest: CSV source -> validated, partitioned Parquet.

Usage:
    python ingest/ingest.py --source data/sample/cpi_fixture.csv --out warehouse/bronze

The source contract (schema) is validated BEFORE anything is written.
Every row is stamped with provenance (source_name, fetched_at) at write time.
Writes are idempotent upserts keyed on (date, item_code): re-ingesting the
same data never creates duplicates; a newer value for an existing key wins.
Output is partitioned by year: warehouse/bronze/cpi/year=YYYY/data.parquet
Exit code 0 = PASS, 1 = FAIL. A machine-readable check block is printed.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {
    "date": "datetime64[ns]",
    "item_code": "object",
    "item_name": "object",
    "index_value": "float64",
}

PROVENANCE_COLUMNS = ["source_name", "fetched_at"]

# Upsert key: one observation per (date, item_code).
UPSERT_KEY = ["date", "item_code"]


class ValidationError(Exception):
    pass


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the bronze contract. Fail fast, never write bad data."""
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValidationError(f"missing columns: {sorted(missing)}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="ISO8601")
    df["index_value"] = pd.to_numeric(df["index_value"], errors="coerce")

    if df["date"].isna().any():
        raise ValidationError("unparseable dates found")
    if df["index_value"].isna().any():
        raise ValidationError("non-numeric index_value found")
    if (df["index_value"] <= 0).any():
        raise ValidationError("index_value must be > 0")

    dupes = df.duplicated(subset=UPSERT_KEY).sum()
    if dupes:
        raise ValidationError(f"{dupes} duplicate (date, item_code) rows")

    return df


def add_provenance(
    df: pd.DataFrame, source_name: str, fetched_at: str | None = None
) -> pd.DataFrame:
    """Stamp every row with where it came from and when it was fetched.

    fetched_at is stored as an ISO-8601 UTC string (portable across
    Parquet readers; silver casts it to a timestamp).
    """
    if not source_name:
        raise ValidationError("source_name must be non-empty")
    df = df.copy()
    df["source_name"] = source_name
    df["fetched_at"] = fetched_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    return df


def write_bronze(df: pd.DataFrame, out_dir: Path) -> list[Path]:
    """Idempotent, partitioned upsert into the bronze lake.

    For each year partition: if a Parquet file already exists, merge the
    incoming rows with the existing ones. On key collision (date, item_code)
    the INCOMING row wins (latest fetch is the truth). Re-running the same
    ingest therefore changes nothing but the fetched_at stamp.
    """
    for col in PROVENANCE_COLUMNS:
        if col not in df.columns:
            raise ValidationError(
                f"provenance column '{col}' missing - call add_provenance() first"
            )

    written: list[Path] = []
    for year, part in df.groupby(df["date"].dt.year):
        target = out_dir / "cpi" / f"year={year}"
        target.mkdir(parents=True, exist_ok=True)
        path = target / "data.parquet"

        if path.exists():
            existing = pd.read_parquet(path)
            existing["date"] = pd.to_datetime(existing["date"])
            merged = pd.concat([existing, part], ignore_index=True)
            merged = merged.drop_duplicates(subset=UPSERT_KEY, keep="last")
        else:
            merged = part

        merged = merged.sort_values(UPSERT_KEY).reset_index(drop=True)
        merged.to_parquet(path, index=False)
        written.append(path)
    return written


def count_bronze_rows(out_dir: Path) -> int:
    """Total rows currently in the bronze lake (for idempotency proofs)."""
    files = sorted(out_dir.glob("cpi/year=*/data.parquet"))
    return sum(len(pd.read_parquet(f)) for f in files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="warehouse/bronze")
    parser.add_argument(
        "--source-name",
        default=None,
        help="Provenance label (defaults to the source file name)",
    )
    args = parser.parse_args()

    source_name = args.source_name or Path(args.source).name

    checks: list[tuple[str, str]] = []
    try:
        df = pd.read_csv(args.source)
        checks.append(("read_source", f"PASS ({len(df)} rows)"))
        df = validate(df)
        checks.append(("validate_contract", "PASS"))
        df = add_provenance(df, source_name)
        checks.append(("add_provenance", f"PASS (source_name={source_name})"))
        written = write_bronze(df, Path(args.out))
        total = count_bronze_rows(Path(args.out))
        checks.append(
            ("write_partitions", f"PASS ({len(written)} partitions, {total} rows total)")
        )
        status = 0
    except (ValidationError, FileNotFoundError, ValueError) as exc:
        checks.append(("pipeline", f"FAIL - {exc}"))
        status = 1

    print("===== OTOMATIK KONTROL =====")
    for name, result in checks:
        print(f"{name}: {result}")
    print(f"RESULT: {'PASS' if status == 0 else 'FAIL'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
