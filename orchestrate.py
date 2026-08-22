"""Single-entrypoint orchestrator for the econ-lakehouse pipeline.

Runs the full flow: (live EVDS fetch | synthetic fixture) -> bronze ingest
-> idempotency proof -> dbt build (silver/gold + tests) -> gold sanity check.

Every execution — successful or failed — appends one row to the run audit
log at `warehouse/run_log.parquet` (see `observability/run_log.py`), so the
pipeline has a durable operational history instead of only console output.

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
RUN_LOG = ROOT / "warehouse" / "run_log.parquet"

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


def _record_run(
    *,
    run_id: str,
    started_at: str,
    t0: float,
    status: str,
    mode: str,
    source_name: str,
    bronze_rows: int,
    gold_rows: int,
    failed_step: str = "",
) -> None:
    """Append this execution to the audit log; never break the pipeline.

    Observability must not become a new failure mode. Everything here —
    including the import — is guarded, and `BaseException` is caught (not
    just `Exception`) so that a `SystemExit` escaping the audit path can
    never mask the pipeline's own error or exit code.
    """
    if not run_id:
        # The observability import failed at startup; nothing to record.
        return
    try:
        from observability.run_log import RunRecord, append_run, git_sha, summarize

        append_run(
            RUN_LOG,
            RunRecord(
                run_id=run_id,
                started_at_utc=started_at,
                ended_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                duration_seconds=round(time.monotonic() - t0, 3),
                status=status,
                mode=mode,
                source_name=source_name,
                bronze_rows=int(bronze_rows),
                gold_rows=int(gold_rows),
                steps_total=len(RESULTS),
                steps_failed=sum(1 for _, s, _ in RESULTS if s == "FAIL"),
                git_sha=git_sha(ROOT),
                failed_step=failed_step,
            ),
        )
        log.info("run log appended: %s (%s)", RUN_LOG, status)
        log.info("run history (last 5):\n%s", summarize(RUN_LOG))
    except BaseException as exc:  # pragma: no cover - defensive
        log.warning("run log write failed (non-fatal): %s", exc)


def main() -> int:
    sys.path.insert(0, str(ROOT))

    # Guarded: if the observability layer cannot even be imported, the
    # pipeline still runs — it just runs without an audit row.
    try:
        from observability.run_log import new_run_id, utc_now

        run_id = new_run_id()
        started_at = utc_now()
    except BaseException as exc:  # pragma: no cover - defensive
        log.warning("run log unavailable (non-fatal): %s", exc)
        run_id = ""
        started_at = ""
    t0 = time.monotonic()

    api_key = os.environ.get("EVDS_API_KEY", "").strip()
    mode = "live" if api_key else "fixture"
    source_name = "evds:TP.FG.J0" if api_key else "fixture:synthetic"
    bronze_rows = 0
    gold_rows = 0

    try:
        if api_key:
            source_csv = "data/evds/cpi_evds.csv"
            run_step(
                "fetch-evds-live",
                [sys.executable, "ingest/evds_client.py",
                 "--series", "TP.FG.J0", "--start", "2015-01", "--out", source_csv],
            )
        else:
            log.warning("EVDS_API_KEY not set -> using synthetic fixture (NOT real data)")
            source_csv = "data/sample/cpi_fixture.csv"

        ingest_cmd = [
            sys.executable, "ingest/ingest.py",
            "--source", source_csv, "--out", "warehouse/bronze",
            "--source-name", source_name,
        ]
        run_step("ingest-bronze", ingest_cmd)

        # Idempotency proof: re-ingest must not change row count.
        from ingest.ingest import count_bronze_rows  # noqa: E402

        before = count_bronze_rows(BRONZE)
        run_step("re-ingest (idempotency)", ingest_cmd)
        after = count_bronze_rows(BRONZE)
        bronze_rows = after
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
        gold_rows = n
        RESULTS.append(("gold-sanity", "PASS" if n > 0 else "FAIL", 0.0))

        # Persist data provenance next to the warehouse so downstream consumers
        # (dashboard banner, self-healing bootstrap) can tell fixture from live
        # long after this process exits. The boot event is ephemeral; the file
        # is the durable source of truth.
        provenance = {
            "mode": mode,
            "source_name": source_name,
            "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gold_rows": n,
        }
        PROVENANCE.parent.mkdir(parents=True, exist_ok=True)
        PROVENANCE.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        log.info("provenance written: %s -> %s", PROVENANCE, provenance["mode"])

        overall = all(s == "PASS" for _, s, _ in RESULTS)
    except BaseException as exc:
        failed = next((name for name, s, _ in RESULTS if s == "FAIL"), type(exc).__name__)
        _record_run(
            run_id=run_id, started_at=started_at, t0=t0, status="failure",
            mode=mode, source_name=source_name, bronze_rows=bronze_rows,
            gold_rows=gold_rows, failed_step=str(failed),
        )
        raise

    _record_run(
        run_id=run_id, started_at=started_at, t0=t0,
        status="success" if overall else "failure",
        mode=mode, source_name=source_name, bronze_rows=bronze_rows,
        gold_rows=gold_rows,
        failed_step="" if overall else next(
            (name for name, s, _ in RESULTS if s == "FAIL"), ""),
    )

    print("===== OTOMATIK KONTROL =====")
    for step, status, dt in RESULTS:
        print(f"{step}: {status}" + (f" ({dt:.1f}s)" if dt else ""))
    print(f"source: {source_name}")
    print(f"provenance: {mode}")
    print(f"gold_rows: {gold_rows}")
    print(f"run_id: {run_id}")
    print(f"RESULT: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
