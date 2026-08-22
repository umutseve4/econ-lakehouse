"""Fail a production run when a CSV's newest observation exceeds the policy."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quality.freshness import (  # noqa: E402
    MAX_LAG_MONTHS,
    freshness_state,
    normalize_observation_date,
)


def newest_observation(csv_path: Path) -> str:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        raw_dates = [
            row.get("date", "").strip() for row in csv.DictReader(handle)
        ]
    raw_dates = [value for value in raw_dates if value]
    if not raw_dates:
        raise ValueError(f"no observation dates found in {csv_path}")
    newest = max(normalize_observation_date(value) for value in raw_dates)
    return newest.isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--max-lag-months", type=int, default=MAX_LAG_MONTHS)
    args = parser.parse_args()

    try:
        newest = newest_observation(args.csv)
        severity, lag, message = freshness_state(
            newest, max_lag_months=args.max_lag_months
        )
    except (OSError, ValueError) as exc:
        print("===== OTOMATIK KONTROL =====")
        print(f"error: {exc}")
        print("RESULT: FAIL")
        return 1

    passed = severity == "success"
    print("===== OTOMATIK KONTROL =====")
    print(f"newest_observation: {newest}")
    print(f"lag_months: {lag}")
    print(f"max_lag_months: {args.max_lag_months}")
    print(f"message: {message}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
