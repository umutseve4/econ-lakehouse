"""Failure-path contract for the M12 run audit log.

The happy-path end-to-end proof shows that a successful run is recorded.
It cannot show the two invariants that actually matter during an incident:

  1. A pipeline failure still appends exactly one `failure` row, and the
     original exception propagates untouched (the exit code stays honest).
  2. If the audit write itself blows up, the pipeline's own exit code is
     unchanged — observability must never become a new failure mode.

Both are proved here by fault injection against the real orchestrator.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import observability.run_log as run_log  # noqa: E402
import orchestrate  # noqa: E402

TOTAL = 0
FAILED = 0


def check(name: str, cond: bool) -> None:
    global TOTAL, FAILED
    TOTAL += 1
    if not cond:
        FAILED += 1
    print(f"{name}: {'PASS' if cond else 'FAIL'}")


def main() -> int:
    log_path = orchestrate.RUN_LOG
    before = len(run_log.read_runs(log_path))

    # --- 1. an injected step failure is recorded and re-raised -----------
    original_run_step = orchestrate.run_step

    def boom(name, argv, env=None):
        orchestrate.RESULTS.append((name, "FAIL", 0.0))
        raise SystemExit(f"injected failure: {name}")

    orchestrate.run_step = boom
    raised: BaseException | None = None
    try:
        orchestrate.main()
    except BaseException as exc:  # noqa: BLE001 - that is the point
        raised = exc
    finally:
        orchestrate.run_step = original_run_step
        orchestrate.RESULTS.clear()

    check("pipeline failure propagates", isinstance(raised, SystemExit))

    df = run_log.read_runs(log_path)
    check("exactly one new row written", len(df) == before + 1)
    if len(df):
        row = df.iloc[-1]
        check("new row status is failure", str(row["status"]) == "failure")
        check("failed_step is recorded", str(row["failed_step"]).strip() != "")
        check("run_id is recorded", str(row["run_id"]).strip() != "")
        check("steps_failed is positive", int(row["steps_failed"]) >= 1)

    # --- 2. an audit-write failure must not change the exit code ---------
    mid = len(run_log.read_runs(log_path))
    original_append = run_log.append_run

    def explode(*args, **kwargs):
        raise RuntimeError("injected audit write failure")

    run_log.append_run = explode
    orchestrate.RESULTS.clear()
    code: int | None = None
    crashed: BaseException | None = None
    try:
        code = orchestrate.main()
    except BaseException as exc:  # noqa: BLE001
        crashed = exc
    finally:
        run_log.append_run = original_append
        orchestrate.RESULTS.clear()

    check("audit failure does not crash the pipeline", crashed is None)
    check("pipeline exit code unaffected by audit failure", code == 0)
    check("no row written when the audit write fails",
          len(run_log.read_runs(log_path)) == mid)

    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {TOTAL}")
    print(f"tests_failed: {FAILED}")
    print(f"RESULT: {'PASS' if FAILED == 0 else 'FAIL'}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
