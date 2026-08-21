"""Dagster software-defined assets for the econ-lakehouse pipeline.

Maps the existing orchestrate.py flow onto an asset graph so the pipeline
gains lineage, per-asset metadata, and schedulability from an orchestrator
instead of a hand-rolled script:

    bronze_cpi  --->  warehouse_marts  (+ gold_nonempty asset check)

Each asset shells out to the same battle-tested entrypoints CI already
verifies (ingest/ingest.py, dbt build), so orchestration adds coordination
without forking the pipeline logic.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
from dagster import (
    AssetCheckResult,
    MaterializeResult,
    MetadataValue,
    asset,
    asset_check,
)

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "warehouse" / "bronze"
DB_PATH = ROOT / "warehouse" / "econ.duckdb"
GOLD_TABLE = "mart_inflation_yoy"


def _run(argv: list[str], env: dict | None = None) -> None:
    proc = subprocess.run(argv, cwd=ROOT, env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise RuntimeError(f"subprocess failed ({proc.returncode}): {argv}")


def _count_bronze() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from ingest.ingest import count_bronze_rows

    return count_bronze_rows(BRONZE)


@asset(description="Validated, partitioned bronze Parquet lake (CPI).")
def bronze_cpi() -> MaterializeResult:
    api_key = os.environ.get("EVDS_API_KEY", "").strip()
    if api_key:
        source_csv = "data/evds/cpi_evds.csv"
        source_name = "evds:TP.FG.J0"
        _run([sys.executable, "ingest/evds_client.py",
              "--series", "TP.FG.J0", "--start", "2015-01", "--out", source_csv])
    else:
        source_csv = "data/sample/cpi_fixture.csv"
        source_name = "fixture:synthetic"

    ingest_cmd = [sys.executable, "ingest/ingest.py",
                  "--source", source_csv, "--out", "warehouse/bronze",
                  "--source-name", source_name]
    _run(ingest_cmd)

    # Idempotency proof stays inside the asset: a second materialization
    # of the same input must not change the lake.
    before = _count_bronze()
    _run(ingest_cmd)
    after = _count_bronze()
    if not (before == after and before > 0):
        raise RuntimeError(f"idempotency violated: before={before} after={after}")

    return MaterializeResult(metadata={
        "rows": MetadataValue.int(after),
        "source": MetadataValue.text(source_name),
        "idempotency": MetadataValue.text("PASS"),
    })


@asset(deps=[bronze_cpi],
       description="dbt-built silver views and gold marts on DuckDB.")
def warehouse_marts() -> MaterializeResult:
    dbt_cmd = (["dbt"] if shutil.which("dbt")
               else [sys.executable, "-m", "dbt.cli.main"])
    _run([*dbt_cmd, "build", "--project-dir", "."],
         env={"DBT_PROFILES_DIR": str(ROOT)})

    con = duckdb.connect(str(DB_PATH), read_only=True)
    gold_rows = con.execute(f"select count(*) from {GOLD_TABLE}").fetchone()[0]
    con.close()
    return MaterializeResult(metadata={"gold_rows": MetadataValue.int(gold_rows)})


@asset_check(asset=warehouse_marts,
             description="Gold mart must be non-empty after every build.")
def gold_nonempty() -> AssetCheckResult:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    n = con.execute(f"select count(*) from {GOLD_TABLE}").fetchone()[0]
    con.close()
    return AssetCheckResult(passed=n > 0, metadata={"gold_rows": n})
