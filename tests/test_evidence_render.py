"""Tests for the static evidence page.

The page is itself a claim about the pipeline, so these tests are mostly
about the ways a page can *lie*: showing a green state while the schedule
has stopped, hiding days on which nothing ran, absorbing missing days into
a success rate, or rendering ledger content as markup.

``build_site`` is pure, so every one of these is a plain in-memory check
with no filesystem, no clock and no network.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from evidence.render import (
    DEFAULT_WINDOW_DAYS,
    LedgerError,
    PageMeta,
    STATE_FAILING,
    STATE_NO_EVIDENCE,
    STATE_OK,
    STATE_STALE,
    build_site,
    parse_ts,
    summarize_window,
    window_days_list,
)
from observability.run_log import RUN_LOG_COLUMNS

NOW = datetime(2026, 9, 20, 6, 0, 0, tzinfo=timezone.utc)


def make_run(started: datetime, status: str = "success", **overrides):
    """One ledger row with sane defaults; overrides let a test bend one field."""
    row = {
        "run_id": overrides.pop("run_id", f"run-{started.isoformat()}"),
        "started_at_utc": started.isoformat(timespec="seconds"),
        "ended_at_utc": (started + timedelta(seconds=42)).isoformat(timespec="seconds"),
        "duration_seconds": 42.0,
        "status": status,
        "mode": "fixture",
        "source_name": "evds_fixture",
        "bronze_rows": 1200,
        "gold_rows": 240,
        "steps_total": 6,
        "steps_failed": 0 if status == "success" else 1,
        "git_sha": "a" * 40,
        "failed_step": "" if status == "success" else "dbt_test",
    }
    row.update(overrides)
    return row


def frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(list(rows))
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})
    return df[RUN_LOG_COLUMNS]


def daily(n: int, *, end: datetime = NOW, status: str = "success"):
    """``n`` consecutive daily runs ending on the day of ``end``."""
    return [make_run(end - timedelta(days=i), status=status) for i in range(n)]


# ---------------------------------------------------------------- window ---


def test_window_is_utc_calendar_days_inclusive_of_today():
    days = window_days_list(NOW, 14)
    assert len(days) == 14
    assert days[-1] == "2026-09-20"
    assert days[0] == "2026-09-07"
    assert days == sorted(days), "days must be oldest-first"


def test_window_rejects_non_positive():
    with pytest.raises(ValueError):
        window_days_list(NOW, 0)


def test_run_just_before_window_start_is_excluded():
    """23:59:59 on the day before the window must not sneak in."""
    outside = datetime(2026, 9, 6, 23, 59, 59, tzinfo=timezone.utc)
    inside = datetime(2026, 9, 7, 0, 0, 0, tzinfo=timezone.utc)
    s = summarize_window(frame([make_run(outside), make_run(inside)]), NOW)
    assert s.total_runs == 1
    assert s.days[0].day == "2026-09-07"
    assert len(s.days[0].runs) == 1


def test_utc_day_boundary_assigns_run_to_the_right_day():
    late = datetime(2026, 9, 19, 23, 59, 59, tzinfo=timezone.utc)
    early = datetime(2026, 9, 20, 0, 0, 0, tzinfo=timezone.utc)
    s = summarize_window(frame([make_run(late), make_run(early)]), NOW)
    by_day = {d.day: d for d in s.days}
    assert len(by_day["2026-09-19"].runs) == 1
    assert len(by_day["2026-09-20"].runs) == 1


# ---------------------------------------------------------------- counts ---


def test_missing_days_are_counted_and_never_absorbed_into_success_rate():
    """Four runs across a fourteen-day window is ten missing days, not 100% health."""
    runs = [make_run(NOW - timedelta(days=i)) for i in (0, 1, 5, 9)]
    s = summarize_window(frame(runs), NOW)
    assert s.expected_days == 14
    assert s.observed_days == 4
    assert s.missing_days == 10
    assert s.total_runs == 4
    assert s.success_runs == 4
    assert s.failed_runs == 0
    assert s.observed_days + s.missing_days == s.expected_days

    files = build_site(frame(runs), NOW)
    html = files["index.html"]
    assert "4/14" in html
    assert html.count("MISSING — no run recorded on this UTC day") == 10


def test_multiple_runs_in_one_day_count_once_as_an_observed_day():
    a = NOW - timedelta(hours=1)
    b = NOW - timedelta(hours=5)
    s = summarize_window(frame([make_run(a), make_run(b)]), NOW)
    assert s.total_runs == 2
    assert s.observed_days == 1
    assert s.missing_days == 13


def test_observed_equals_days_with_at_least_one_run():
    runs = daily(3) + [make_run(NOW - timedelta(days=1, hours=3), status="failure")]
    s = summarize_window(frame(runs), NOW)
    assert s.total_runs == 4
    assert s.success_runs == 3
    assert s.failed_runs == 1
    assert s.success_runs + s.failed_runs == s.total_runs
    assert s.observed_days == 3
    mixed = [d for d in s.days if d.status == "mixed"]
    assert len(mixed) == 1 and mixed[0].day == "2026-09-19"


def test_duplicate_run_ids_are_both_counted_but_render_deterministically():
    """The ledger dedupes by run_id; the renderer must not silently reorder."""
    a = make_run(NOW - timedelta(hours=2), run_id="dup")
    b = make_run(NOW - timedelta(hours=1), run_id="dup")
    first = build_site(frame([a, b]), NOW)["runs.json"]
    second = build_site(frame([b, a]), NOW)["runs.json"]
    assert first == second, "render must not depend on input row order"


# ----------------------------------------------------------------- state ---


def test_empty_ledger_is_no_evidence_not_success():
    s = summarize_window(frame([]), NOW)
    assert s.state == STATE_NO_EVIDENCE
    assert s.total_runs == 0
    assert s.latest_run_at is None
    html = build_site(frame([]), NOW)["index.html"]
    assert "NO EVIDENCE" in html
    # An empty ledger renders as fourteen explicit MISSING days, not as a
    # short, tidy, misleadingly empty table.
    assert html.count("MISSING — no run recorded on this UTC day") == 14


def test_ledger_with_rows_but_all_outside_window_is_no_evidence():
    old = [make_run(NOW - timedelta(days=40))]
    s = summarize_window(frame(old), NOW)
    assert s.state == STATE_NO_EVIDENCE
    assert s.ledger_rows_total == 1
    assert s.total_runs == 0


def test_stale_outranks_success():
    """A successful run three days ago must not render as a healthy page."""
    s = summarize_window(
        frame([make_run(NOW - timedelta(days=3))]), NOW, stale_after_hours=30
    )
    assert s.state == STATE_STALE
    assert s.latest_status == "success"
    assert s.age_hours == pytest.approx(72.0, abs=0.1)


def test_failing_latest_run_sets_failing_state():
    runs = daily(3, end=NOW - timedelta(hours=3)) + [
        make_run(NOW - timedelta(minutes=10), status="failure")
    ]
    s = summarize_window(frame(runs), NOW)
    assert s.state == STATE_FAILING
    assert s.latest_status == "failure"
    assert s.latest_success_at is not None, "an earlier success is still reported"


def test_fresh_success_is_ok():
    s = summarize_window(frame(daily(14)), NOW)
    assert s.state == STATE_OK
    assert s.observed_days == 14
    assert s.missing_days == 0


def test_age_boundary_is_strict():
    """Exactly at the limit is not yet stale; one second past it is."""
    at_limit = summarize_window(
        frame([make_run(NOW - timedelta(hours=30))]), NOW, stale_after_hours=30
    )
    past = summarize_window(
        frame([make_run(NOW - timedelta(hours=30, minutes=1))]),
        NOW,
        stale_after_hours=30,
    )
    assert at_limit.state == STATE_OK
    assert past.state == STATE_STALE


# ------------------------------------------------------------- robustness ---


def test_missing_columns_raise_ledger_error():
    df = frame(daily(2)).drop(columns=["gold_rows"])
    with pytest.raises(LedgerError):
        summarize_window(df, NOW)


def test_malformed_rows_are_excluded_and_reported_not_dropped_silently():
    good = make_run(NOW - timedelta(hours=1))
    bad_ts = make_run(NOW - timedelta(hours=2), run_id="x1")
    bad_ts["started_at_utc"] = "not-a-timestamp"
    bad_status = make_run(NOW - timedelta(hours=3), run_id="x2", status="success")
    bad_status["status"] = "maybe"
    empty_id = make_run(NOW - timedelta(hours=4), run_id="   ")

    s = summarize_window(frame([good, bad_ts, bad_status, empty_id]), NOW)
    assert s.total_runs == 1
    assert s.malformed_rows == 3
    assert s.ledger_rows_total == 4
    html = build_site(frame([good, bad_ts, bad_status, empty_id]), NOW)["index.html"]
    assert "could not be parsed" in html


def test_all_rows_malformed_is_no_evidence():
    bad = make_run(NOW, run_id="only")
    bad["started_at_utc"] = ""
    s = summarize_window(frame([bad]), NOW)
    assert s.state == STATE_NO_EVIDENCE
    assert s.malformed_rows == 1


def test_null_row_counts_do_not_crash_the_render():
    row = make_run(NOW - timedelta(hours=1))
    row["bronze_rows"] = None
    row["gold_rows"] = float("nan")
    row["duration_seconds"] = None
    files = build_site(frame([row]), NOW)
    assert "—" in files["index.html"]
    payload = json.loads(files["runs.json"])
    run = payload["days"][-1]["runs"][0]
    assert run["bronze_rows"] is None
    assert run["gold_rows"] is None


def test_naive_timestamps_are_treated_as_utc():
    assert parse_ts("2026-09-20T05:00:00") == datetime(
        2026, 9, 20, 5, 0, tzinfo=timezone.utc
    )
    assert parse_ts("2026-09-20T05:00:00Z") == datetime(
        2026, 9, 20, 5, 0, tzinfo=timezone.utc
    )
    assert parse_ts("") is None
    assert parse_ts(None) is None


def test_non_utc_offset_is_normalised_before_day_bucketing():
    """03:00+04:00 is 23:00 the previous UTC day and must bucket there."""
    row = make_run(NOW)
    row["started_at_utc"] = "2026-09-20T03:00:00+04:00"
    s = summarize_window(frame([row]), NOW)
    by_day = {d.day: d for d in s.days}
    assert len(by_day["2026-09-19"].runs) == 1
    assert by_day["2026-09-20"].status == "missing"


# ------------------------------------------------------------------ html ---


def test_ledger_content_is_escaped_not_executed():
    row = make_run(NOW - timedelta(hours=1), status="failure")
    row["failed_step"] = '<script>alert("xss")</script>'
    row["mode"] = '"><img src=x onerror=alert(1)>'
    html = build_site(frame([row]), NOW)["index.html"]
    # No raw tag may survive: the payload must appear only as inert text.
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_page_carries_machine_readable_freshness_attributes():
    html = build_site(frame(daily(2)), NOW, PageMeta(stale_after_hours=30))["index.html"]
    assert 'data-generated-at="2026-09-20T06:00:00Z"' in html
    assert 'data-stale-after-hours="30"' in html
    assert 'data-latest-run-at="2026-09-20T06:00:00Z"' in html
    assert "id=\"freshness-live\"" in html


def test_page_refuses_forbidden_reliability_claims():
    """The page must never claim more than a fixture run can support."""
    html = build_site(frame(daily(14)), NOW)["index.html"].lower()
    for banned in (
        "real-time",
        "realtime",
        "production-ready",
        "uptime",
        "always-on",
        "24/7",
        "live data",
    ):
        assert banned not in html, f"page must not claim {banned!r}"


def test_page_states_its_scope_and_data_mode():
    html = build_site(frame(daily(3)), NOW)["index.html"]
    assert "DATA MODE: SYNTHETIC FIXTURE" in html
    assert "Does not prove:" in html
    assert "upstream" in html


def test_noscript_fallback_warns_instead_of_claiming_freshness():
    html = build_site(frame(daily(3)), NOW)["index.html"]
    assert "<noscript>" in html
    assert "Freshness not verified" in html


def test_provenance_is_rendered_from_meta():
    meta = PageMeta(
        source_sha="deadbeef" * 5,
        run_url="https://github.com/o/r/actions/runs/7",
        ledger_ref="branch: evidence",
        repo_url="https://github.com/o/r",
        schedule_desc="daily, 05:23 UTC",
    )
    html = build_site(frame(daily(2)), NOW, meta)["index.html"]
    assert "https://github.com/o/r/actions/runs/7" in html
    assert "branch: evidence" in html
    assert "daily, 05:23 UTC" in html
    assert "deadbeef" in html


def test_json_and_html_agree_on_every_headline_count():
    runs = daily(5) + [make_run(NOW - timedelta(days=2, hours=2), status="failure")]
    files = build_site(frame(runs), NOW)
    payload = json.loads(files["runs.json"])
    html = files["index.html"]
    c = payload["counts"]
    assert c["runs_total"] == 6
    assert c["runs_success"] == 5
    assert c["runs_failed"] == 1
    assert c["observed_days"] == 5
    assert c["missing_days"] == 9
    assert f'{c["observed_days"]}/{c["expected_days"]}' in html
    assert f'{c["runs_success"]}/{c["runs_total"]}' in html


def test_payload_is_stable_and_hashed():
    a = json.loads(build_site(frame(daily(4)), NOW)["runs.json"])
    b = json.loads(build_site(frame(daily(4)), NOW + timedelta(seconds=0))["runs.json"])
    assert a["content_sha256"] == b["content_sha256"]
    assert len(a["content_sha256"]) == 64
    assert a["renderer_version"]
    assert a["schema_version"] == 1


def test_content_hash_changes_when_the_data_changes():
    a = json.loads(build_site(frame(daily(4)), NOW)["runs.json"])["content_sha256"]
    b = json.loads(build_site(frame(daily(5)), NOW)["runs.json"])["content_sha256"]
    assert a != b


def test_window_size_is_configurable_and_respected_everywhere():
    files = build_site(frame(daily(10)), NOW, PageMeta(window_days=7))
    payload = json.loads(files["runs.json"])
    assert payload["window"]["days"] == 7
    assert payload["counts"]["expected_days"] == 7
    assert payload["counts"]["observed_days"] == 7
    assert len(payload["days"]) == 7
    assert "Last 7 UTC days" in files["index.html"]


def test_default_window_is_fourteen_days():
    payload = json.loads(build_site(frame(daily(1)), NOW)["runs.json"])
    assert payload["window"]["days"] == DEFAULT_WINDOW_DAYS == 14


def test_table_is_newest_first():
    files = build_site(frame(daily(3)), NOW)
    html = files["index.html"]
    rows = re.findall(r"2026-09-(\d\d)", html)
    days_in_table = [r for r in rows]
    assert days_in_table[0] == "20", "newest UTC day must be the first table row"


def test_invalid_meta_is_rejected():
    with pytest.raises(ValueError):
        PageMeta(window_days=0)
    with pytest.raises(ValueError):
        PageMeta(stale_after_hours=0)


def test_non_dataframe_ledger_is_rejected():
    with pytest.raises(LedgerError):
        summarize_window([], NOW)  # type: ignore[arg-type]
