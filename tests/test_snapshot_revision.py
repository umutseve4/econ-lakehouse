"""Late-revision end-to-end test: dbt snapshot must capture a CPI revision.

Run in CI AFTER the pipeline has populated warehouse/bronze and dbt build
has run (dbt is required on PATH or as a module).

Scenario:
  1. dbt snapshot            -> baseline: 1 version per key
  2. re-ingest ONE observation with a revised index_value (x 1.01)
  3. dbt snapshot            -> the revised key must now have 2 versions,
                                exactly 1 closed (dbt_valid_to set), and the
                                open version must carry the revised value.

Prints an OTOMATIK KONTROL block; exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
import pandas as pd


def run_dbt(*args: str) -> None:
    dbt = shutil.which("dbt")
    cmd = [dbt] if dbt else [sys.executable, "-m", "dbt.cli.main"]
    env = dict(os.environ, DBT_PROFILES_DIR=str(ROOT))
    subprocess.run(
        [*cmd, *args, "--project-dir", str(ROOT)], check=True, env=env, cwd=ROOT
    )


def snapshot_table(con: duckdb.DuckDBPyConnection) -> str:
    schema = con.execute(
        "select table_schema from information_schema.tables "
        "where table_name = 'snap_cpi' limit 1"
    ).fetchone()
    assert schema, "snap_cpi table not found — did dbt snapshot run?"
    return f'"{schema[0]}".snap_cpi'


def main() -> int:
    checks: list[tuple[str, str]] = []
    status = 0
    try:
        # Pick one real key from bronze.
        files = sorted((ROOT / "warehouse" / "bronze").glob("cpi/year=*/data.parquet"))
        assert files, "bronze lake is empty — run the pipeline first"
        first = pd.read_parquet(files[0]).sort_values(["date", "item_code"]).iloc[0]
        key_date = pd.Timestamp(first["date"]).date().isoformat()
        key_code = str(first["item_code"])
        orig = float(first["index_value"])
        revised_val = round(orig * 1.01, 4)
        checks.append(("pick_key", f"PASS ({key_date}, {key_code}, orig={orig})"))

        # 1) Baseline snapshot.
        run_dbt("snapshot")
        con = duckdb.connect(str(ROOT / "warehouse" / "econ.duckdb"))
        tbl = snapshot_table(con)
        v0 = con.execute(
            f"select count(*) from {tbl} where obs_date = ? and item_code = ?",
            [key_date, key_code],
        ).fetchone()[0]
        con.close()
        checks.append(("baseline_versions", f"{'PASS' if v0 == 1 else 'FAIL'} ({v0})"))
        assert v0 == 1, f"expected 1 baseline version, got {v0}"

        # 2) Ingest a revised observation for the same key.
        with tempfile.TemporaryDirectory() as tmp:
            csv = Path(tmp) / "revision.csv"
            pd.DataFrame(
                {
                    "date": [key_date],
                    "item_code": [key_code],
                    "item_name": [str(first["item_name"])],
                    "index_value": [revised_val],
                }
            ).to_csv(csv, index=False)
            subprocess.run(
                [
                    sys.executable, "ingest/ingest.py",
                    "--source", str(csv),
                    "--out", "warehouse/bronze",
                    "--source-name", "revision:test",
                ],
                check=True,
                cwd=ROOT,
            )
        checks.append(("ingest_revision", f"PASS (revised={revised_val})"))

        # 3) Snapshot again -> history must show the revision.
        run_dbt("snapshot")
        con = duckdb.connect(str(ROOT / "warehouse" / "econ.duckdb"))
        rows = con.execute(
            f"select index_value, dbt_valid_to from {tbl} "
            "where obs_date = ? and item_code = ? order by dbt_valid_from",
            [key_date, key_code],
        ).fetchall()
        con.close()

        versions = len(rows)
        closed = sum(1 for r in rows if r[1] is not None)
        current = [r[0] for r in rows if r[1] is None]
        ok = (
            versions == 2
            and closed == 1
            and len(current) == 1
            and abs(current[0] - revised_val) < 1e-9
        )
        checks.append(("versions_after_revision", f"{'PASS' if versions == 2 else 'FAIL'} ({versions})"))
        checks.append(("closed_versions", f"{'PASS' if closed == 1 else 'FAIL'} ({closed})"))
        checks.append(
            ("current_value_is_revised",
             f"{'PASS' if ok else 'FAIL'} (current={current[0] if current else None})")
        )
        assert ok
    except Exception as exc:  # noqa: BLE001
        checks.append(("snapshot_test", f"FAIL — {exc}"))
        status = 1

    print("===== OTOMATIK KONTROL =====")
    for name, result in checks:
        print(f"{name}: {result}")
    print(f"RESULT: {'PASS' if status == 0 else 'FAIL'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
