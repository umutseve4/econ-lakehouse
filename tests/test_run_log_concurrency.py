"""Concurrency proofs for the run audit ledger (M13).

The M12 ledger appended by reading the whole Parquet file, concatenating
one row and writing it back. That is a read-modify-write, and two runs
overlapping between the read and the write silently erased one of them.

This file is deliberately structured as *proof*, not as reassurance:

1. `prove_legacy_loses_a_row` reimplements the old append and replays an
   explicit interleaving that loses a run. Without this, the rest only
   shows the new code works — not that the bug was ever real.
2. `prove_current_survives_same_interleaving` puts the current
   implementation through that identical interleaving.
3. `prove_pre_m13_history_is_preserved` writes a legacy single-file
   ledger, then appends with the current code and requires the old rows
   to still be readable.
4. `prove_retried_write_does_not_duplicate` re-records one run_id.
5. `prove_concurrent_processes_all_survive` starts 12 real OS processes
   released by a shared wall-clock barrier and requires all 12 rows.

Run directly (`python tests/test_run_log_concurrency.py`) or under
pytest; every check prints PASS/FAIL and the script exits non-zero on the
first failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from observability import run_log
from observability.run_log import RUN_LOG_COLUMNS, RunRecord

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not condition:
        FAILURES.append(label)


def make_record(n: int, started: str | None = None) -> RunRecord:
    return RunRecord(
        run_id=f"run-{n:04d}",
        started_at_utc=started or f"2026-01-01T00:{n:02d}:00+00:00",
        ended_at_utc=f"2026-01-01T00:{n:02d}:30+00:00",
        duration_seconds=float(n),
        status="success",
        mode="fixture",
        source_name="synthetic",
        bronze_rows=100 + n,
        gold_rows=10 + n,
        steps_total=4,
        steps_failed=0,
        git_sha="0" * 40,
        failed_step="",
    )


# --------------------------------------------------------------------------
# 1. The bug that M13 removes — reproduced, not asserted.
# --------------------------------------------------------------------------

def legacy_read(path: Path) -> pd.DataFrame:
    """The M12 read: one file, or empty."""
    if not path.is_file():
        return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})
    return pd.read_parquet(path)[RUN_LOG_COLUMNS]


def legacy_write(path: Path, frame: pd.DataFrame, record: RunRecord) -> None:
    """The M12 write: concatenate onto the snapshot this writer read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = pd.DataFrame([asdict(record)])[RUN_LOG_COLUMNS]
    pd.concat([frame, row], ignore_index=True)[RUN_LOG_COLUMNS].to_parquet(
        path, index=False
    )


def prove_legacy_loses_a_row() -> None:
    print("\n1. previous read-modify-write append")
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "run_log.parquet"

        # Interleaving: A reads, B reads, A writes, B writes.
        snapshot_a = legacy_read(ledger)
        snapshot_b = legacy_read(ledger)
        legacy_write(ledger, snapshot_a, make_record(1))
        legacy_write(ledger, snapshot_b, make_record(2))

        ids = set(pd.read_parquet(ledger)["run_id"])
        check(
            "legacy append loses an overlapping run",
            ids == {"run-0002"},
            f"ledger contains {sorted(ids)}; run-0001 was erased",
        )


# --------------------------------------------------------------------------
# 2. Same interleaving, current implementation.
# --------------------------------------------------------------------------

def prove_current_survives_same_interleaving() -> None:
    print("\n2. current per-part layout, identical interleaving")
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "run_log.parquet"

        run_log.read_runs(ledger)  # A reads
        run_log.read_runs(ledger)  # B reads
        run_log.write_part(ledger, make_record(1))  # A writes
        run_log.write_part(ledger, make_record(2))  # B writes
        run_log.compact(ledger)

        ids = set(run_log.read_runs(ledger)["run_id"])
        check(
            "both runs survive the interleaving that broke the legacy append",
            ids == {"run-0001", "run-0002"},
            f"ledger contains {sorted(ids)}",
        )

        snapshot_ids = set(pd.read_parquet(ledger)["run_id"])
        check(
            "derived snapshot agrees with the parts",
            snapshot_ids == ids,
            f"snapshot contains {sorted(snapshot_ids)}",
        )

        parts = sorted(p.name for p in run_log.parts_dir(ledger).glob("*.parquet"))
        check("one part file per run", len(parts) == 2, ", ".join(parts))

        leftovers = [
            p.name
            for p in run_log.parts_dir(ledger).iterdir()
            if not p.name.endswith(".parquet")
        ]
        check(
            "no temporary files left behind",
            not leftovers,
            ", ".join(leftovers) or "clean",
        )


# --------------------------------------------------------------------------
# 3. History written before M13 must not disappear.
# --------------------------------------------------------------------------

def prove_pre_m13_history_is_preserved() -> None:
    print("\n3. pre-M13 history after migration")
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "run_log.parquet"

        legacy = pd.DataFrame([asdict(make_record(1)), asdict(make_record(2))])
        ledger.parent.mkdir(parents=True, exist_ok=True)
        legacy[RUN_LOG_COLUMNS].to_parquet(ledger, index=False)

        run_log.append_run(ledger, make_record(3))
        df = run_log.read_runs(ledger)

        check(
            "legacy rows still readable",
            set(df["run_id"]) == {"run-0001", "run-0002", "run-0003"},
            f"{sorted(df['run_id'])}",
        )
        check(
            "no duplication of migrated rows",
            len(df) == 3,
            f"{len(df)} rows",
        )
        check(
            "chronological order preserved",
            list(df["run_id"]) == ["run-0001", "run-0002", "run-0003"],
            " -> ".join(df["run_id"]),
        )


# --------------------------------------------------------------------------
# 4. A retried write must not duplicate history.
# --------------------------------------------------------------------------

def prove_retried_write_does_not_duplicate() -> None:
    print("\n4. retried write of the same run_id")
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "run_log.parquet"

        run_log.append_run(ledger, make_record(1))
        retried = RunRecord(**{**asdict(make_record(1)), "gold_rows": 999})
        run_log.append_run(ledger, retried)

        df = run_log.read_runs(ledger)
        check("retry stays one row", len(df) == 1, f"{len(df)} rows")
        check(
            "retry wins",
            int(df.iloc[0]["gold_rows"]) == 999,
            f"gold_rows={df.iloc[0]['gold_rows']}",
        )


# --------------------------------------------------------------------------
# 5. Real parallel processes, released together.
# --------------------------------------------------------------------------

WORKER = """
import sys, time
from pathlib import Path
sys.path.insert(0, {root!r})
from observability import run_log
from observability.run_log import RunRecord

ledger, n, release = Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
while time.time() < release:
    time.sleep(0.001)
run_log.append_run(ledger, RunRecord(
    run_id="proc-%04d" % n,
    started_at_utc="2026-02-01T00:%02d:00+00:00" % n,
    ended_at_utc="2026-02-01T00:%02d:30+00:00" % n,
    duration_seconds=float(n),
    status="success",
    mode="fixture",
    source_name="synthetic",
    bronze_rows=n,
    gold_rows=n,
    steps_total=4,
    steps_failed=0,
    git_sha="0"*40,
    failed_step="",
))
"""


def prove_concurrent_processes_all_survive(workers: int = 12) -> None:
    print(f"\n5. {workers} concurrent OS processes")
    root = str(Path(__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "run_log.parquet"
        script = Path(tmp) / "worker.py"
        script.write_text(WORKER.format(root=root), encoding="utf-8")

        release = time.time() + 3.0
        env = {**os.environ, "PYTHONPATH": root}
        procs = [
            subprocess.Popen(
                [sys.executable, str(script), str(ledger), str(i), str(release)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            for i in range(1, workers + 1)
        ]
        failed = []
        for i, p in enumerate(procs, start=1):
            _, err = p.communicate(timeout=180)
            if p.returncode != 0:
                failed.append(f"worker {i}: {err.decode('utf-8', 'replace')[-300:]}")

        check("every writer exited cleanly", not failed, " | ".join(failed) or "12/12")

        df = run_log.read_runs(ledger)
        expected = {f"proc-{i:04d}" for i in range(1, workers + 1)}
        missing = sorted(expected - set(df["run_id"]))
        check(
            "no run lost under real parallelism",
            not missing,
            f"{len(df)}/{workers} rows" + (f", missing {missing}" if missing else ""),
        )
        check(
            "no run duplicated",
            len(df) == len(set(df["run_id"])),
            f"{len(df)} rows, {len(set(df['run_id']))} distinct",
        )

        snapshot = set(pd.read_parquet(ledger)["run_id"])
        check(
            "derived snapshot is complete after concurrent writes",
            snapshot == expected,
            f"snapshot has {len(snapshot)}/{workers}",
        )


def test_run_log_concurrency() -> None:
    """pytest entry point — same proofs, one assertion."""
    main()


def main() -> int:
    prove_legacy_loses_a_row()
    prove_current_survives_same_interleaving()
    prove_pre_m13_history_is_preserved()
    prove_retried_write_does_not_duplicate()
    prove_concurrent_processes_all_survive()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {FAILURES}")
        raise AssertionError(f"{len(FAILURES)} concurrency check(s) failed: {FAILURES}")
    print("All concurrency checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
