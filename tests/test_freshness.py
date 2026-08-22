"""Deterministic boundary tests for the freshness policy and gate input."""

from __future__ import annotations

import csv
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.freshness_gate import newest_observation
from quality.freshness import freshness_state, observation_lag_months


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, condition))
        print(f"{name}: {'PASS' if condition else 'FAIL'}")

    as_of = date(2026, 8, 22)
    check("lag_same_month", observation_lag_months("2026-08-01", as_of) == 0)
    check("lag_three_months", observation_lag_months("2026-05-31", as_of) == 3)
    check("lag_four_months", observation_lag_months("2026-04-01", as_of) == 4)

    fresh = freshness_state("2026-05-01", as_of)
    stale = freshness_state("2026-04-01", as_of)
    check("boundary_3_months_passes", fresh[0] == "success" and fresh[1] == 3)
    check("boundary_4_months_fails", stale[0] == "error" and stale[1] == 4)
    check("fresh_message_has_exact_date", "2026-05-01" in fresh[2])
    check("stale_message_disclaims_current", "not current" in stale[2])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "observations.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "item_code"])
            writer.writeheader()
            writer.writerows(
                [
                    {"date": "2026-01-01", "item_code": "CP00"},
                    {"date": "2025-12-01", "item_code": "CP00"},
                ]
            )
        check("csv_newest_observation", newest_observation(path) == "2026-01-01")

    failed = sum(not ok for _, ok in checks)
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(checks)}")
    print(f"tests_failed: {failed}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
