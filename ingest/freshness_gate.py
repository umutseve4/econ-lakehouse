"""Fail a production run when a CSV's newest observation exceeds the policy.

The gate reports one of three states:

``fresh``
    Inside the policy window. Exit 0.
``acknowledged_stale``
    Outside the window, but an exact match for a documented upstream freeze
    that is still inside its review period. Exit 0, with a loud warning — the
    data is stale and every line of output says so.
``stale``
    Outside the window for any other reason, including an expired
    acknowledgement or a freeze that has moved. Exit 1.

The acknowledgement lives in ``ingest/freshness_waiver.py`` and is CI-only. The
dashboard calls ``quality.freshness`` directly and therefore still reports an
acknowledged freeze as an error to human readers, which is the correct
behaviour: users must never be shown stale data described as current.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, timezone, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.freshness_waiver import (  # noqa: E402
    ACKNOWLEDGED_STALE,
    FRESH,
    STALE,
    evaluate_ci_freshness,
)
from quality.freshness import (  # noqa: E402
    MAX_LAG_MONTHS,
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


def _emit_annotation(state: str, message: str) -> None:
    """Surface the verdict to GitHub Actions as a first-class annotation.

    An acknowledged freeze exits 0, so without this it would be invisible in
    the run summary — a green check with a hidden caveat is precisely the
    failure mode this whole design exists to avoid.
    """
    if state == ACKNOWLEDGED_STALE:
        print(f"::warning title=Acknowledged stale data::{message}")
    elif state == STALE:
        print(f"::error title=Data freshness gate failed::{message}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(f"### Freshness gate: `{state}`\n\n{message}\n\n")
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--max-lag-months", type=int, default=MAX_LAG_MONTHS)
    parser.add_argument(
        "--series",
        default=None,
        help=(
            "Upstream series identifier. Required for an acknowledged freeze to "
            "match; omitting it means no waiver can apply."
        ),
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO date to evaluate against. Defaults to today in UTC.",
    )
    args = parser.parse_args(argv)

    try:
        as_of = (
            date.fromisoformat(args.as_of)
            if args.as_of
            else datetime.now(timezone.utc).date()
        )
        newest = newest_observation(args.csv)
        state, lag, message = evaluate_ci_freshness(
            newest,
            series_code=args.series,
            as_of=as_of,
            max_lag_months=args.max_lag_months,
        )
    except (OSError, ValueError) as exc:
        print("===== OTOMATIK KONTROL =====")
        print(f"error: {exc}")
        print("RESULT: FAIL")
        return 1

    passed = state in (FRESH, ACKNOWLEDGED_STALE)
    _emit_annotation(state, message)

    print("===== OTOMATIK KONTROL =====")
    print(f"series: {args.series or '(not supplied)'}")
    print(f"newest_observation: {newest}")
    print(f"lag_months: {lag}")
    print(f"max_lag_months: {args.max_lag_months}")
    print(f"as_of: {as_of.isoformat()}")
    print(f"state: {state}")
    print(f"message: {message}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
