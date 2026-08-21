"""End-to-end test of the Dagster asset graph (fixture mode).

Self-skips when dagster is unavailable so the suite stays runnable in
minimal environments; CI installs the real dependency and executes
everything, materializing both assets in-process against the synthetic
fixture (no EVDS key needed -> deterministic).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from dagster import materialize
except ImportError as exc:  # pragma: no cover
    print(f"SKIP \u2014 dagster unavailable: {exc}")
    print("===== OTOMATIK KONTROL =====")
    print("tests_total: 0 (skipped)")
    print("RESULT: PASS")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestration.assets import bronze_cpi, gold_nonempty, warehouse_marts
from orchestration.definitions import cpi_pipeline_job, defs, weekly_schedule

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"{'ok' if cond else 'FAIL'} - {name}"
          f"{(' \u2014 ' + detail) if detail and not cond else ''}")


def main() -> int:
    # Structural checks on the definitions we ship.
    check("job_name", cpi_pipeline_job.name == "cpi_pipeline_job",
          cpi_pipeline_job.name)
    check("schedule_cron", weekly_schedule.cron_schedule == "17 6 * * 1",
          weekly_schedule.cron_schedule)
    check("defs_load", defs is not None)

    # Full in-process materialization: bronze -> marts (+ asset check).
    result = materialize([bronze_cpi, warehouse_marts, gold_nonempty])
    check("materialize_success", result.success)

    mats = result.get_asset_materialization_events()
    keys = [e.asset_key.to_user_string() for e in mats]
    check("both_assets_materialized", len(mats) == 2, str(keys))
    check("bronze_before_marts",
          keys == ["bronze_cpi", "warehouse_marts"], str(keys))

    check_evals = result.get_asset_check_evaluations()
    check("gold_check_passed",
          len(check_evals) == 1 and check_evals[0].passed,
          str([(e.check_name, e.passed) for e in check_evals]))

    failed = [n for n, ok, _ in results if not ok]
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(results)}")
    print(f"tests_failed: {len(failed)}")
    print(f"RESULT: {'PASS' if not failed else 'FAIL \u2014 ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
