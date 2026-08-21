"""Bronze-layer ingest: CSV source -> validated, partitioned Parquet.

Usage:
    python ingest/ingest.py --source data/sample/cpi_fixture.csv --out warehouse/bronze

The source contract (schema) is validated BEFORE anything is written.
Output is partitioned by year: warehouse/bronze/cpi/year=YYYY/data.parquet
Exit code 0 = PASS, 1 = FAIL. A machine-readable check block is printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {
    "date": "datetime64[ns]",
    "item_code": "object",
    "item_name": "object",
    "index_value": "float64",
}


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

    dupes = df.duplicated(subset=["date", "item_code"]).sum()
    if dupes:
        raise ValidationError(f"{dupes} duplicate (date, item_code) rows")

    return df


def write_bronze(df: pd.DataFrame, out_dir: Path) -> list[Path]:
    written: list[Path] = []
    for year, part in df.groupby(df["date"].dt.year):
        target = out_dir / "cpi" / f"year={year}"
        target.mkdir(parents=True, exist_ok=True)
        path = target / "data.parquet"
        part.to_parquet(path, index=False)
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="warehouse/bronze")
    args = parser.parse_args()

    checks: list[tuple[str, str]] = []
    try:
        df = pd.read_csv(args.source)
        checks.append(("read_source", f"PASS ({len(df)} rows)"))
        df = validate(df)
        checks.append(("validate_contract", "PASS"))
        written = write_bronze(df, Path(args.out))
        checks.append(("write_partitions", f"PASS ({len(written)} partitions)"))
        status = 0
    except (ValidationError, FileNotFoundError, ValueError) as exc:
        checks.append(("pipeline", f"FAIL — {exc}"))
        status = 1

    print("===== OTOMATIK KONTROL =====")
    for name, result in checks:
        print(f"{name}: {result}")
    print(f"RESULT: {'PASS' if status == 0 else 'FAIL'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
