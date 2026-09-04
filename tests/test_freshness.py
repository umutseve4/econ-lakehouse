"""Deterministic boundary tests for the freshness policy, gate and waiver.

Everything here is offline and clock-independent: every assertion passes an
explicit ``as_of``, so these tests mean the same thing on any day. They run on
every push and pull request, while the live EVDS gate runs only on a schedule.

The waiver tests matter more than the policy tests. A time-boxed
acknowledgement that silently matched too much would be worse than no gate at
all, so the bulk of this file is negative: proving the waiver does *not* apply
to the wrong series, the wrong month, or the wrong date.
"""

from __future__ import annotations

import csv
import io
import contextlib
import sys
import tempfile
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest import freshness_gate
from ingest.freshness_gate import newest_observation
from ingest.freshness_waiver import (
    ACKNOWLEDGED_STALE,
    FRESH,
    STALE,
    WAIVERS,
    FreshnessWaiver,
    WaiverConfigError,
    evaluate_ci_freshness,
    observation_month,
)
from quality.freshness import freshness_state, observation_lag_months

REPO_ROOT = Path(__file__).resolve().parents[1]

# The production waiver, restated here so the tests pin the exact values that
# were reviewed. If someone edits the register, these tests fail and force the
# change to be acknowledged rather than absorbed.
PROD = WAIVERS[0]
FROZEN_OBS = "2026-01-01"


def _raises(fn) -> bool:
    """True when constructing an invalid waiver is rejected."""
    try:
        fn()
    except (WaiverConfigError, FrozenInstanceError, TypeError, ValueError):
        return True
    return False


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, condition))
        print(f"{name}: {'PASS' if condition else 'FAIL'}")

    # ------------------------------------------------------------------
    # Shared policy boundaries (unchanged behaviour).
    # ------------------------------------------------------------------
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
                    {"date": "2026-9", "item_code": "CP00"},
                    {"date": "2026-10", "item_code": "CP00"},
                    {"date": "2025-12-01", "item_code": "CP00"},
                ]
            )
        check(
            "csv_newest_observation_unpadded_months",
            newest_observation(path) == "2026-10-01",
        )

    # ------------------------------------------------------------------
    # The reviewed waiver record itself.
    # ------------------------------------------------------------------
    check("register_has_single_waiver", len(WAIVERS) == 1)
    check("waiver_series_is_exact", PROD.series_code == "TP.FG.J0")
    check("waiver_frozen_at_is_2026_01", PROD.frozen_at == "2026-01")
    check("waiver_accepted_on", PROD.accepted_on == date(2026, 9, 4))
    check("waiver_review_by", PROD.review_by == date(2026, 10, 5))
    check("waiver_names_an_owner", bool(PROD.owner.strip()))
    check("waiver_cites_evidence", PROD.evidence == "docs/data-freshness.md")
    check("waiver_links_tracking_issue", "issues/32" in PROD.issue)

    check("observation_month_pads", observation_month("2026-1-1") == "2026-01")

    # ------------------------------------------------------------------
    # Positive: the acknowledged freeze passes CI, inside the window only.
    # ------------------------------------------------------------------
    state, lag, message = evaluate_ci_freshness(
        FROZEN_OBS, series_code="TP.FG.J0", as_of=date(2026, 9, 7)
    )
    check("known_freeze_is_acknowledged", state == ACKNOWLEDGED_STALE)
    check("known_freeze_reports_true_lag", lag == 8)
    check("acknowledged_message_says_stale", "STALE" in message)
    # The narrative must never call the data fresh. Reference fields (evidence
    # path, tracking URL) legitimately contain the substring "freshness", so
    # they are stripped before the assertion — what is checked is the claim,
    # not the file names.
    narrative = message
    for reference in (PROD.evidence, PROD.issue):
        narrative = narrative.replace(reference, "")
    check("acknowledged_message_never_says_fresh", "fresh" not in narrative.lower())
    check("acknowledged_message_has_expiry", "2026-10-05" in message)
    check("acknowledged_message_has_owner", PROD.owner in message)
    check("acknowledged_message_links_issue", "issues/32" in message)

    # Every scheduled Monday inside the window is acknowledged.
    mondays_in_window = ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
    check(
        "all_four_scheduled_mondays_acknowledged",
        all(
            evaluate_ci_freshness(
                FROZEN_OBS, series_code="TP.FG.J0", as_of=date.fromisoformat(d)
            )[0]
            == ACKNOWLEDGED_STALE
            for d in mondays_in_window
        ),
    )

    # ------------------------------------------------------------------
    # Negative: the waiver must not stretch. These are the load-bearing tests.
    # ------------------------------------------------------------------
    def state_for(**kwargs) -> str:
        params = {
            "observed_on": FROZEN_OBS,
            "series_code": "TP.FG.J0",
            "as_of": date(2026, 9, 7),
        }
        params.update(kwargs)
        return evaluate_ci_freshness(
            params["observed_on"],
            series_code=params["series_code"],
            as_of=params["as_of"],
        )[0]

    check("expiry_is_exclusive_on_review_by", state_for(as_of=date(2026, 10, 5)) == STALE)
    check("expired_after_review_by", state_for(as_of=date(2026, 10, 12)) == STALE)
    check("before_accepted_on_does_not_match", state_for(as_of=date(2026, 9, 3)) == STALE)
    check("wrong_series_does_not_match", state_for(series_code="TP.TUFE1YI.T1") == STALE)
    check("missing_series_does_not_match", state_for(series_code=None) == STALE)
    check("empty_series_does_not_match", state_for(series_code="") == STALE)
    check(
        "advanced_freeze_month_does_not_match",
        state_for(observed_on="2026-02-01") == STALE,
    )
    check(
        "earlier_freeze_month_does_not_match",
        state_for(observed_on="2025-12-01") == STALE,
    )
    check(
        "unrelated_old_observation_is_stale",
        state_for(observed_on="2024-06-01") == STALE,
    )

    # A waiver must never manufacture a pass for data that is actually fresh —
    # nor suppress the normal fresh path.
    fresh_state, fresh_lag, _ = evaluate_ci_freshness(
        "2026-09-01", series_code="TP.FG.J0", as_of=date(2026, 9, 7)
    )
    check("fresh_data_is_fresh_not_acknowledged", fresh_state == FRESH)
    check("fresh_data_lag_zero", fresh_lag == 0)

    # ------------------------------------------------------------------
    # Fail-closed construction: malformed waivers must raise, never soften.
    # ------------------------------------------------------------------
    def make(**over) -> FreshnessWaiver:
        base = dict(
            series_code="TP.FG.J0",
            frozen_at="2026-01",
            accepted_on=date(2026, 9, 4),
            review_by=date(2026, 10, 5),
            owner="umutseve4",
            evidence="docs/data-freshness.md",
            issue="https://example.invalid/32",
        )
        base.update(over)
        return FreshnessWaiver(**base)

    check("valid_waiver_constructs", isinstance(make(), FreshnessWaiver))
    check("rejects_wildcard_series", _raises(lambda: make(series_code="TP.FG.*")))
    check("rejects_empty_series", _raises(lambda: make(series_code="  ")))
    check("rejects_unpadded_month", _raises(lambda: make(frozen_at="2026-1")))
    check("rejects_month_13", _raises(lambda: make(frozen_at="2026-13")))
    check("rejects_full_date_as_month", _raises(lambda: make(frozen_at="2026-01-01")))
    check("rejects_string_review_by", _raises(lambda: make(review_by="2026-10-05")))
    check("rejects_string_accepted_on", _raises(lambda: make(accepted_on="2026-09-04")))
    check(
        "rejects_review_by_before_accepted_on",
        _raises(lambda: make(review_by=date(2026, 9, 1))),
    )
    check(
        "rejects_review_by_equal_accepted_on",
        _raises(lambda: make(review_by=date(2026, 9, 4))),
    )
    check("rejects_empty_owner", _raises(lambda: make(owner="")))
    check("rejects_empty_evidence", _raises(lambda: make(evidence="")))
    check("rejects_empty_issue", _raises(lambda: make(issue="")))
    check("rejects_unknown_field", _raises(lambda: make(reason="because")))
    check("waiver_is_immutable", _raises(lambda: setattr(make(), "review_by", date(2027, 1, 1))))

    # Duplicate registers are rejected.
    from ingest.freshness_waiver import _validate_register

    check(
        "rejects_duplicate_series_in_register",
        _raises(lambda: _validate_register((make(), make(frozen_at="2026-02")))),
    )
    check(
        "rejects_non_waiver_in_register",
        _raises(lambda: _validate_register(("not-a-waiver",))),
    )

    # ------------------------------------------------------------------
    # Dashboard isolation. The waiver is CI-only and must never reach a user.
    # ------------------------------------------------------------------
    same_obs_dashboard = freshness_state(FROZEN_OBS, date(2026, 9, 7))
    check(
        "dashboard_still_reports_error_for_acknowledged_freeze",
        same_obs_dashboard[0] == "error",
    )
    check(
        "dashboard_message_still_disclaims_current",
        "not current" in same_obs_dashboard[2],
    )

    policy_src = (REPO_ROOT / "quality" / "freshness.py").read_text(encoding="utf-8")
    check("shared_policy_has_no_waiver_knowledge", "waiver" not in policy_src.lower())

    dashboard_dir = REPO_ROOT / "dashboard"
    dashboard_sources = sorted(dashboard_dir.glob("*.py"))
    check("dashboard_sources_found", len(dashboard_sources) > 0)
    check(
        "dashboard_never_imports_waiver",
        all(
            "freshness_waiver" not in p.read_text(encoding="utf-8")
            for p in dashboard_sources
        ),
    )

    # ------------------------------------------------------------------
    # The production CLI itself, called directly — not a reimplementation.
    # ------------------------------------------------------------------
    def run_cli(rows: list[str], *extra: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "obs.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                handle.write("date,item_code\n")
                for row in rows:
                    handle.write(f"{row},CP00\n")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = freshness_gate.main(
                    ["--csv", str(csv_path), *extra]
                )
            return code, buffer.getvalue()

    code, out = run_cli(
        ["2025-12-01", FROZEN_OBS],
        "--series", "TP.FG.J0", "--as-of", "2026-09-07",
    )
    check("cli_acknowledged_exits_zero", code == 0)
    check("cli_acknowledged_reports_state", "state: acknowledged_stale" in out)
    check("cli_acknowledged_emits_warning", "::warning title=" in out)
    check("cli_acknowledged_result_pass", "RESULT: PASS" in out)

    code, out = run_cli(
        ["2025-12-01", FROZEN_OBS],
        "--series", "TP.FG.J0", "--as-of", "2026-10-05",
    )
    check("cli_expired_exits_one", code == 1)
    check("cli_expired_reports_stale", "state: stale" in out)
    check("cli_expired_emits_error", "::error title=" in out)
    check("cli_expired_result_fail", "RESULT: FAIL" in out)

    code, out = run_cli(["2025-12-01", FROZEN_OBS], "--as-of", "2026-09-07")
    check("cli_without_series_exits_one", code == 1)
    check("cli_without_series_reports_stale", "state: stale" in out)

    code, out = run_cli(
        ["2026-08-01", "2026-09-01"],
        "--series", "TP.FG.J0", "--as-of", "2026-09-07",
    )
    check("cli_fresh_exits_zero", code == 0)
    check("cli_fresh_reports_fresh", "state: fresh" in out)
    check("cli_fresh_emits_no_annotation", "::warning" not in out and "::error" not in out)

    code, out = run_cli(
        ["2026-02-01"],
        "--series", "TP.FG.J0", "--as-of", "2026-09-07",
    )
    check("cli_moved_freeze_exits_one", code == 1)
    check("cli_moved_freeze_reports_stale", "state: stale" in out)

    failed = sum(not ok for _, ok in checks)
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(checks)}")
    print(f"tests_failed: {failed}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
