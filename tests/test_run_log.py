"""Contract tests for the pipeline run audit log (observability layer)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from observability.run_log import (
    RUN_LOG_COLUMNS,
    RunRecord,
    append_run,
    git_sha,
    new_run_id,
    read_runs,
    summarize,
    utc_now,
)


def make_record(**overrides) -> RunRecord:
    base = dict(
        run_id=new_run_id(),
        started_at_utc="2026-08-22T07:00:00+00:00",
        ended_at_utc="2026-08-22T07:01:00+00:00",
        duration_seconds=60.0,
        status="success",
        mode="fixture",
        source_name="fixture:synthetic",
        bronze_rows=1200,
        gold_rows=1100,
        steps_total=6,
        steps_failed=0,
        git_sha="0" * 40,
        failed_step="",
    )
    base.update(overrides)
    return RunRecord(**base)


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))
        print(f"{name}: {'PASS' if condition else 'FAIL'}")

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "warehouse" / "run_log.parquet"

        # Absent log reads as empty, with the full schema present.
        empty = read_runs(log)
        check("absent_log_reads_empty", empty.empty)
        check("empty_log_has_schema", list(empty.columns) == RUN_LOG_COLUMNS)
        check("summary_of_empty_log", summarize(log) == "run_log: empty")

        # First append creates the file with exactly one row.
        append_run(log, make_record(run_id="run-a"))
        one = read_runs(log)
        check("first_append_creates_file", log.exists())
        check("first_append_one_row", len(one) == 1)
        check("columns_stable", list(one.columns) == RUN_LOG_COLUMNS)

        # Append-only: history accumulates, prior rows are never rewritten.
        append_run(log, make_record(run_id="run-b", gold_rows=1101))
        two = read_runs(log)
        check("append_is_additive", len(two) == 2)
        check("history_preserved", two.iloc[0]["run_id"] == "run-a")
        check("run_ids_unique", two["run_id"].nunique() == 2)

        # Failures must be recorded too — a success-only log hides incidents.
        append_run(
            log,
            make_record(
                run_id="run-c",
                status="failure",
                steps_failed=1,
                failed_step="dbt-build",
                gold_rows=0,
            ),
        )
        three = read_runs(log)
        failed = three[three["status"] == "failure"]
        check("failure_row_recorded", len(failed) == 1)
        check("failed_step_captured", failed.iloc[0]["failed_step"] == "dbt-build")
        check("mixed_statuses_coexist", three["status"].nunique() == 2)

        # The audit table is DuckDB-queryable with the same engine as the marts.
        import duckdb

        con = duckdb.connect()
        n = con.sql(f"select count(*) from '{log.as_posix()}'").fetchone()[0]
        check("duckdb_can_query_run_log", n == 3)

        # Summary renders the tail without raising.
        text = summarize(log, last=2)
        check("summary_renders_tail", text.count("\n") == 1 and "success" in text)

    # Invariants that protect the log from silent corruption.
    try:
        make_record(status="ok")
        bad_status_rejected = False
    except ValueError:
        bad_status_rejected = True
    check("invalid_status_rejected", bad_status_rejected)

    try:
        make_record(duration_seconds=-1.0)
        bad_duration_rejected = False
    except ValueError:
        bad_duration_rejected = True
    check("negative_duration_rejected", bad_duration_rejected)

    check("run_id_is_unique", new_run_id() != new_run_id())
    check("utc_now_is_iso_utc", utc_now().endswith("+00:00"))
    check("git_sha_never_empty", len(git_sha()) > 0)

    failed_count = sum(not ok for _, ok in checks)
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(checks)}")
    print(f"tests_failed: {failed_count}")
    print(f"pandas: {pd.__version__}")
    print(f"RESULT: {'PASS' if failed_count == 0 else 'FAIL'}")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
