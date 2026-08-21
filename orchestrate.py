"""Single-entrypoint orchestrator for the econ-lakehouse pipeline.

Runs the full flow: (live EVDS fetch | synthetic fixture) -> bronze ingest
-> idempotency proof -> dbt build (silver/gold + tests) -> gold sanity check.

Used as the Docker container entrypoint and runnable locally:

    EVDS_API_KEY=... python orchestrate.py          # live mode
    python orchestrate.py                           # fixture mode

Exit code 0 = all steps passed; non-zero = first failing step.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("orchestrator")

ROOT = Path(__file__).resolve().parent
BRONZE = ROOT / "warehouse" / "bronze"
PROVENANCE = ROOT / "warehouse" / "provenance.json"

RESULTS: list[tuple[str, str, float]] = []  # (step, PASS/FAIL, seconds)


def run_step(name: str, argv: list[str], env: dict | None = None) -> None:
    """Run one pipeline step as a subprocess; raise on failure."""
    log.info("step start: %s", name)
    t0 = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, env={**os.environ, **(env or {})})
    dt = time.monotonic() - t0
    status = "PASS" if proc.returncode == 0 else "FAIL"
    RESULTS.append((name, status, dt))
    log.info("step end:   %s -> %s (%.1fs)", name, status, dt)
    if proc.returncode != 0:
        raise SystemExit(f"step failed: {name} (exit {proc.returncode})")


def main() -> int:
    api_key = os.environ.get("EVDS_API_KEY", "").strip()

    if api_key:
        source_csv = "data/evds/cpi_evds.csv"
        source_name = "evds:TP.FG.J0"
        run_step(
            "fetch-evds-live",
            [sys.executable, "ingest/evds_client.py",
             "--series", "TP.FG.J0", "--start", "2015-01", "--out", source_csv],
        )
    else:
        log.warning("EVDS_API_KEY not set -> using synthetic fixture (NOT real data)")
        source_csv = "data/sample/cpi_fixture.csv"
        source_name = "fixture:synthetic"

    ingest_cmd = [
        sys.executable, "ingest/ingest.py",
        "--source", source_csv, "--out", "warehouse/bronze",
        "--source-name", source_name,
    ]
    run_step("ingest-bronze", ingest_cmd)

    # Idempotency proof: re-ingest must not change row count.
    sys.path.insert(0, str(ROOT))
    from ingest.ingest import count_bronze_rows  # noqa: E402

    before = count_bronze_rows(BRONZE)
    run_step("re-ingest (idempotency)", ingest_cmd)
    after = count_bronze_rows(BRONZE)
    idem_ok = before == after and before > 0
    RESULTS.append(("idempotency-proof", "PASS" if idem_ok else "FAIL", 0.0))
    log.info("idempotency: rows before=%d after=%d -> %s",
             before, after, "PASS" if idem_ok else "FAIL")
    if not idem_ok:
        raise SystemExit("idempotency proof failed")

    # Prefer the console script; fall back to module invocation so the
    # orchestrator also works where only the Python package is importable.
    dbt_cmd = (["dbt"] if shutil.which("dbt")
               else [sys.executable, "-m", "dbt.cli.main"])
    run_step("dbt-build", [*dbt_cmd, "build", "--project-dir", "."],
             env={"DBT_PROFILES_DIR": str(ROOT)})

    # Gold sanity check.
    import duckdb  # noqa: E402
    con = duckdb.connect(str(ROOT / "warehouse" / "econ.duckdb"))
    n = con.sql("select count(*) from mart_inflation_yoy").fetchone()[0]
    RESULTS.append(("gold-sanity", "PASS" if n > 0 else "FAIL", 0.0))

    # Persist data provenance next to the warehouse so downstream consumers
    # (dashboard banner, self-healing bootstrap) can tell fixture from live
    # long after this process exits. The boot event is ephemeral; the file
    # is the durable source of truth.
    provenance = {
        "mode": "live" if api_key else "fixture",
        "source_name": source_name,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gold_rows": n,
    }
    PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
    PROVENANCE.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    log.info("provenance written: %s -> %s", PROVENANCE, provenance["mode"])

    print("===== OTOMATIK KONTROL =====")
    for step, status, dt in RESULTS:
        print(f"{step}: {status}" + (f" ({dt:.1f}s)" if dt else ""))
    print(f"source: {source_name}")
    print(f"provenance: {provenance['mode']}")
    print(f"gold_rows: {n}")
    overall = all(s == "PASS" for _, s, _ in RESULTS)
    print(f"RESULT: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
