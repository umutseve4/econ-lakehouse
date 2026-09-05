"""Render a static, self-auditing evidence page from the run audit ledger.

Why this exists
---------------
A portfolio pipeline is only credible if a stranger can check it without
running anything. The previous public surface was a Streamlit Community
Cloud app, which is put to sleep after a period of inactivity: a reviewer
who opened the link saw a "wake this app" screen, not evidence. This
module produces a **static** page instead, so there is nothing to wake up.

The honest failure mode of a static page is the opposite one: it can keep
serving a cheerful green page long after the pipeline that feeds it has
stopped running. That failure is designed against here in three ways:

1.  The page is *fail-closed on age*. It carries the timestamp it was
    generated at, and re-evaluates its own freshness **in the reader's
    browser at open time**. Once the newest recorded run is older than
    ``stale_after_hours``, the whole page switches to a STALE state. A
    stale page cannot look green.
2.  Missing days are rendered as explicit rows. A daily schedule that
    silently skipped four days shows four ``MISSING`` rows, rather than
    quietly shrinking the table.
3.  Nothing is inferred. ``expected_days``, ``observed_days``,
    ``success``, ``failed`` and ``missing`` are reported separately, with
    raw numerator and denominator, so the reader can redo the division.

Scope, stated plainly
---------------------
The scheduled runs execute the pipeline against a committed synthetic
fixture, not against the live upstream source. The page therefore proves
that the orchestration, validation and audit-ledger path execute and are
recorded; it does **not** prove upstream availability, real data freshness
or any production service level. Those words are deliberately absent from
the rendered output.

Purity
------
``build_site`` is a pure function of ``(runs, now, meta)``. It performs no
I/O, reads no clock and no environment, so every claim the page makes is
reproducible in a unit test. Only ``main`` touches the filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

RENDERER_VERSION = "1.0.0"

DEFAULT_WINDOW_DAYS = 14
DEFAULT_STALE_AFTER_HOURS = 30

#: Ledger columns the page reads. A ledger missing any of these is treated
#: as unreadable rather than silently rendered with blanks.
REQUIRED_COLUMNS = (
    "run_id",
    "started_at_utc",
    "ended_at_utc",
    "duration_seconds",
    "status",
    "mode",
    "source_name",
    "bronze_rows",
    "gold_rows",
    "steps_total",
    "steps_failed",
    "git_sha",
    "failed_step",
)

STATE_OK = "ok"
STATE_FAILING = "failing"
STATE_STALE = "stale"
STATE_NO_EVIDENCE = "no-evidence"

_STATE_HEADLINE = {
    STATE_OK: "RECORDED — newest run succeeded and is within the freshness window",
    STATE_FAILING: "FAILING — the newest recorded run did not succeed",
    STATE_STALE: "STALE — no run recorded inside the freshness window",
    STATE_NO_EVIDENCE: "NO EVIDENCE — the ledger contains no usable run in this window",
}


class LedgerError(ValueError):
    """Raised when the ledger cannot be read as a run ledger at all."""


@dataclass(frozen=True)
class PageMeta:
    """Provenance of one render. Every field is shown on the page."""

    source_sha: str = "unknown"
    run_url: str = ""
    ledger_ref: str = ""
    repo_url: str = ""
    schedule_desc: str = "daily"
    window_days: int = DEFAULT_WINDOW_DAYS
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS

    def __post_init__(self) -> None:
        if self.window_days < 1:
            raise ValueError("window_days must be >= 1")
        if self.stale_after_hours < 1:
            raise ValueError("stale_after_hours must be >= 1")


@dataclass(frozen=True)
class DaySummary:
    """One UTC calendar day inside the window."""

    day: str
    runs: tuple[dict[str, Any], ...] = ()
    status: str = "missing"


@dataclass(frozen=True)
class WindowSummary:
    """Everything the page asserts, computed once and reused by every view."""

    window_start: str
    window_end: str
    expected_days: int
    observed_days: int
    missing_days: int
    total_runs: int
    success_runs: int
    failed_runs: int
    malformed_rows: int
    ledger_rows_total: int
    latest_run_at: str | None
    latest_success_at: str | None
    latest_status: str | None
    age_hours: float | None
    state: str
    days: tuple[DaySummary, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------------
# parsing helpers
# --------------------------------------------------------------------------


def parse_ts(value: Any) -> datetime | None:
    """Parse a ledger timestamp into an aware UTC datetime, or ``None``.

    The ledger writes ``datetime.isoformat(timespec="seconds")`` in UTC, so
    the happy path is exact. Anything unparseable returns ``None`` and is
    counted as a malformed row rather than crashing the render or, worse,
    being silently dropped.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and value != value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value)


def window_days_list(now: datetime, window_days: int) -> list[str]:
    """UTC calendar days in the window, oldest first.

    The window is defined as *UTC calendar days* and includes the day of
    ``now``. This definition is fixed here so that the table, the counts
    and the documentation cannot drift apart into "14 calendar days" in
    one place and "14 x 24 hours" in another.
    """
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    end = now.astimezone(timezone.utc).date()
    return [
        (end - timedelta(days=offset)).isoformat()
        for offset in range(window_days - 1, -1, -1)
    ]


# --------------------------------------------------------------------------
# summarisation
# --------------------------------------------------------------------------


def summarize_window(
    runs: pd.DataFrame,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
) -> WindowSummary:
    """Reduce the ledger to exactly the facts the page is allowed to state.

    Raises :class:`LedgerError` if ``runs`` is not shaped like a ledger. A
    ledger that is merely *empty* is not an error — it is rendered as the
    ``no-evidence`` state, which is a visible, non-green outcome.
    """
    if not isinstance(runs, pd.DataFrame):
        raise LedgerError("run ledger must be a DataFrame")
    missing = [c for c in REQUIRED_COLUMNS if c not in runs.columns]
    if missing:
        raise LedgerError(f"run ledger is missing columns: {missing}")

    now = now.astimezone(timezone.utc)
    days = window_days_list(now, window_days)
    window_start_dt = datetime.fromisoformat(days[0]).replace(tzinfo=timezone.utc)

    by_day: dict[str, list[dict[str, Any]]] = {day: [] for day in days}
    malformed = 0
    ledger_rows_total = int(len(runs))

    for row in runs.to_dict("records"):
        started = parse_ts(row.get("started_at_utc"))
        run_id = _as_text(row.get("run_id")).strip()
        status = _as_text(row.get("status")).strip().lower()
        if started is None or not run_id or status not in {"success", "failure"}:
            malformed += 1
            continue
        if started < window_start_dt:
            continue
        day = started.date().isoformat()
        if day not in by_day:
            # A run stamped in the future relative to ``now``; out of window.
            continue
        ended = parse_ts(row.get("ended_at_utc"))
        by_day[day].append(
            {
                "run_id": run_id,
                "started_at_utc": started.isoformat().replace("+00:00", "Z"),
                "ended_at_utc": (
                    ended.isoformat().replace("+00:00", "Z") if ended else ""
                ),
                "duration_seconds": _as_float(row.get("duration_seconds")),
                "status": status,
                "mode": _as_text(row.get("mode")),
                "source_name": _as_text(row.get("source_name")),
                "bronze_rows": _as_int(row.get("bronze_rows")),
                "gold_rows": _as_int(row.get("gold_rows")),
                "steps_total": _as_int(row.get("steps_total")),
                "steps_failed": _as_int(row.get("steps_failed")),
                "git_sha": _as_text(row.get("git_sha")),
                "failed_step": _as_text(row.get("failed_step")),
                "_sort": started,
            }
        )

    day_summaries: list[DaySummary] = []
    total = success = failed = 0
    observed_days = 0
    latest: dict[str, Any] | None = None
    latest_success: dict[str, Any] | None = None

    for day in days:
        entries = sorted(by_day[day], key=lambda r: (r["_sort"], r["run_id"]))
        for entry in entries:
            total += 1
            if entry["status"] == "success":
                success += 1
                if latest_success is None or entry["_sort"] > latest_success["_sort"]:
                    latest_success = entry
            else:
                failed += 1
            if latest is None or entry["_sort"] > latest["_sort"]:
                latest = entry
        if not entries:
            status = "missing"
        else:
            statuses = {e["status"] for e in entries}
            if statuses == {"success"}:
                status = "success"
            elif statuses == {"failure"}:
                status = "failed"
            else:
                status = "mixed"
            observed_days += 1
        day_summaries.append(
            DaySummary(
                day=day,
                runs=tuple({k: v for k, v in e.items() if k != "_sort"} for e in entries),
                status=status,
            )
        )

    age_hours: float | None = None
    if latest is not None:
        age_hours = round((now - latest["_sort"]).total_seconds() / 3600.0, 2)

    # Fail closed: absence of evidence and staleness both outrank success.
    if latest is None:
        state = STATE_NO_EVIDENCE
    elif age_hours is not None and age_hours > stale_after_hours:
        state = STATE_STALE
    elif latest["status"] != "success":
        state = STATE_FAILING
    else:
        state = STATE_OK

    return WindowSummary(
        window_start=days[0],
        window_end=days[-1],
        expected_days=len(days),
        observed_days=observed_days,
        missing_days=len(days) - observed_days,
        total_runs=total,
        success_runs=success,
        failed_runs=failed,
        malformed_rows=malformed,
        ledger_rows_total=ledger_rows_total,
        latest_run_at=latest["started_at_utc"] if latest else None,
        latest_success_at=(
            latest_success["started_at_utc"] if latest_success else None
        ),
        latest_status=latest["status"] if latest else None,
        age_hours=age_hours,
        state=state,
        days=tuple(day_summaries),
    )


def build_payload(
    summary: WindowSummary, now: datetime, meta: PageMeta
) -> dict[str, Any]:
    """Machine-readable form of the page — the single source both views use."""
    generated_at = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "renderer_version": RENDERER_VERSION,
        "generated_at_utc": generated_at.replace("+00:00", "Z"),
        "data_mode": "synthetic fixture",
        "state": summary.state,
        "window": {
            "definition": "UTC calendar days, inclusive of the generation day",
            "days": summary.expected_days,
            "start": summary.window_start,
            "end": summary.window_end,
        },
        "counts": {
            "expected_days": summary.expected_days,
            "observed_days": summary.observed_days,
            "missing_days": summary.missing_days,
            "runs_total": summary.total_runs,
            "runs_success": summary.success_runs,
            "runs_failed": summary.failed_runs,
            "malformed_ledger_rows": summary.malformed_rows,
            "ledger_rows_total": summary.ledger_rows_total,
        },
        "freshness": {
            "latest_run_at_utc": summary.latest_run_at,
            "latest_run_status": summary.latest_status,
            "latest_success_at_utc": summary.latest_success_at,
            "age_hours_at_generation": summary.age_hours,
            "stale_after_hours": meta.stale_after_hours,
            "schedule": meta.schedule_desc,
        },
        "provenance": {
            "source_sha": meta.source_sha,
            "workflow_run_url": meta.run_url,
            "ledger_ref": meta.ledger_ref,
            "repo_url": meta.repo_url,
        },
        "days": [
            {"day": d.day, "status": d.status, "runs": list(d.runs)}
            for d in summary.days
        ],
    }
    payload["content_sha256"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in payload.items() if k != "generated_at_utc"},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return payload


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#30363d;--fg:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--bad:#f85149;--warn:#d29922;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
main{max-width:1080px;margin:0 auto;padding:32px 20px 72px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:15px;margin:34px 0 10px;color:var(--dim);
text-transform:uppercase;letter-spacing:.08em}
a{color:var(--accent)}
.sub{color:var(--dim);margin:0 0 22px}
.banner{border:1px solid var(--line);border-left-width:5px;border-radius:6px;
padding:14px 16px;margin:0 0 22px;background:var(--panel)}
.banner b{display:block;font-size:16px;margin-bottom:4px}
.banner small{color:var(--dim)}
[data-state="ok"] .banner{border-left-color:var(--ok)}
[data-state="failing"] .banner{border-left-color:var(--bad)}
[data-state="stale"] .banner{border-left-color:var(--warn)}
[data-state="no-evidence"] .banner{border-left-color:var(--bad)}
.scope{border:1px dashed var(--line);border-radius:6px;padding:14px 16px;
background:#12161d;margin:0 0 8px}
.scope p{margin:6px 0}
.tag{display:inline-block;border:1px solid var(--warn);color:var(--warn);
border-radius:4px;padding:1px 7px;font-size:12px;letter-spacing:.06em}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.card .k{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.card .v{font-size:21px;margin-top:3px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);
vertical-align:top;white-space:nowrap}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;
letter-spacing:.05em}
tr.missing td{color:var(--warn);background:rgba(210,153,34,.07)}
tr.failure td{background:rgba(248,81,73,.09)}
.pill{display:inline-block;border-radius:4px;padding:1px 7px;font-size:12px}
.pill.success{background:rgba(63,185,80,.16);color:var(--ok)}
.pill.failure{background:rgba(248,81,73,.16);color:var(--bad)}
.pill.missing{background:rgba(210,153,34,.16);color:var(--warn)}
.pill.mixed{background:rgba(210,153,34,.16);color:var(--warn)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 18px;margin:0;font-size:13px}
dt{color:var(--dim)}
dd{margin:0;word-break:break-all}
.stale-only{display:none}
[data-state="stale"] .stale-only,[data-state="no-evidence"] .stale-only{display:block}
noscript .banner{border-left-color:var(--warn)}
footer{margin-top:40px;color:var(--dim);font-size:12px}
"""

_FRESHNESS_JS = """
(function(){
  var root=document.documentElement;
  var gen=root.getAttribute('data-generated-at');
  var latest=root.getAttribute('data-latest-run-at');
  var limit=parseFloat(root.getAttribute('data-stale-after-hours'));
  var el=document.getElementById('freshness-live');
  if(!el){return;}
  var ref=latest||gen;
  if(!ref||!isFinite(limit)){
    root.setAttribute('data-state','no-evidence');
    el.textContent='Freshness could not be evaluated in the browser; treating this page as unverified.';
    return;
  }
  var age=(Date.now()-Date.parse(ref))/3600000;
  if(!isFinite(age)){
    root.setAttribute('data-state','no-evidence');
    el.textContent='Freshness could not be evaluated in the browser; treating this page as unverified.';
    return;
  }
  var shown=age<1?(Math.round(age*60)+' minutes'):(age.toFixed(1)+' hours');
  el.textContent='Newest recorded run is '+shown+' old, evaluated in your browser just now (limit '+limit+'h).';
  if(age>limit&&root.getAttribute('data-state')!=='no-evidence'){
    root.setAttribute('data-state','stale');
    var h=document.getElementById('state-headline');
    if(h){h.textContent='STALE — this page is being served but its newest run is outside the freshness window';}
  }
})();
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.1f}"
    return f"{value:,}"


def _link(url: str, label: str) -> str:
    if not url:
        return "—"
    return f'<a href="{_esc(url)}" rel="noopener">{_esc(label)}</a>'


def _rows_html(summary: WindowSummary) -> str:
    out: list[str] = []
    for day in reversed(summary.days):
        if not day.runs:
            out.append(
                f'<tr class="missing"><td>{_esc(day.day)}</td>'
                f'<td colspan="8">MISSING — no run recorded on this UTC day</td></tr>'
            )
            continue
        for i, run in enumerate(day.runs):
            cls = "failure" if run["status"] == "failure" else ""
            started = str(run["started_at_utc"])
            clock = started[11:19] if len(started) >= 19 else started
            detail = run["failed_step"] if run["status"] == "failure" else ""
            out.append(
                f'<tr class="{cls}">'
                f"<td>{_esc(day.day if i == 0 else '')}</td>"
                f"<td>{_esc(clock)}</td>"
                f'<td><span class="pill {_esc(run["status"])}">{_esc(run["status"])}</span></td>'
                f"<td>{_esc(run['mode'])}</td>"
                f"<td>{_esc(_fmt_num(run['duration_seconds']))}</td>"
                f"<td>{_esc(_fmt_num(run['bronze_rows']))}</td>"
                f"<td>{_esc(_fmt_num(run['gold_rows']))}</td>"
                f"<td>{_esc(str(run['git_sha'])[:7] or '—')}</td>"
                f"<td>{_esc(detail or run['run_id'][:8])}</td>"
                f"</tr>"
            )
    return "\n".join(out)


def render_html(payload: Mapping[str, Any], summary: WindowSummary, meta: PageMeta) -> str:
    """Render the page. Every number shown comes from ``payload``."""
    counts = payload["counts"]
    fresh = payload["freshness"]
    prov = payload["provenance"]

    denom = counts["runs_total"]
    rate = (
        f'{counts["runs_success"]}/{denom} '
        f'({100.0 * counts["runs_success"] / denom:.0f}%)'
        if denom
        else "0/0 (n/a)"
    )

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append(
        f'<html lang="en" data-state="{_esc(payload["state"])}" '
        f'data-generated-at="{_esc(payload["generated_at_utc"])}" '
        f'data-latest-run-at="{_esc(fresh["latest_run_at_utc"] or "")}" '
        f'data-stale-after-hours="{_esc(meta.stale_after_hours)}">'
    )
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append("<title>econ-lakehouse — pipeline run evidence</title>")
    parts.append(
        '<meta name="description" content="Static, self-auditing record of scheduled '
        'fixture-mode pipeline runs, generated from the Parquet run ledger.">'
    )
    parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body><main>")

    parts.append("<h1>econ-lakehouse — pipeline run evidence</h1>")
    parts.append(
        '<p class="sub">Static page generated from the Parquet run ledger. '
        "Nothing here sleeps, and nothing here needs to be woken up — but read "
        "the scope note before you believe it.</p>"
    )

    parts.append('<div class="banner">')
    parts.append(f'<b id="state-headline">{_esc(_STATE_HEADLINE[payload["state"]])}</b>')
    parts.append(
        f'<small id="freshness-live">Age at generation time: '
        f'{_esc(_fmt_num(fresh["age_hours_at_generation"]))} h '
        f'(limit {_esc(meta.stale_after_hours)} h).</small>'
    )
    parts.append(
        '<p class="stale-only"><small>Because this page is static, it can outlive '
        "the schedule that produces it. The state above is re-checked against your "
        "own clock when you open the page.</small></p>"
    )
    parts.append("</div>")

    parts.append(
        "<noscript><div class=\"banner\"><b>Freshness not verified</b>"
        "<small>JavaScript is disabled, so this page could not re-check its own age "
        "against your clock. Compare <code>generated_at</code> in the provenance "
        "section below against the current time before trusting the state above."
        "</small></div></noscript>"
    )

    parts.append("<h2>What this page does and does not prove</h2>")
    parts.append('<div class="scope">')
    parts.append('<p><span class="tag">DATA MODE: SYNTHETIC FIXTURE</span></p>')
    parts.append(
        "<p><b>Proves:</b> the orchestrator was executed on the schedule below, the "
        "validation steps ran, and every execution — successful or failed — was "
        "recorded in an append-only Parquet audit ledger.</p>"
    )
    parts.append(
        "<p><b>Does not prove:</b> availability of the upstream statistical source, "
        "freshness of real-world data, correctness of published economic figures, or "
        "any service level. The scheduled runs use a committed synthetic fixture; no "
        "credential and no paid resource is involved.</p>"
    )
    parts.append(
        "<p><b>Scheduling caveat:</b> scheduled GitHub Actions runs can be delayed or "
        "dropped under load, and are disabled after a long period of repository "
        "inactivity. Missing days below are shown, not hidden.</p>"
    )
    parts.append("</div>")

    parts.append("<h2>Window counts</h2>")
    cards = [
        ("Window", f'{counts["expected_days"]} UTC days'),
        ("Days with a run", f'{counts["observed_days"]}/{counts["expected_days"]}'),
        ("Days missing", str(counts["missing_days"])),
        ("Runs recorded", str(counts["runs_total"])),
        ("Succeeded", rate),
        ("Failed", str(counts["runs_failed"])),
    ]
    parts.append('<div class="grid">')
    for k, v in cards:
        parts.append(
            f'<div class="card"><div class="k">{_esc(k)}</div>'
            f'<div class="v">{_esc(v)}</div></div>'
        )
    parts.append("</div>")
    parts.append(
        f'<p class="sub" style="margin-top:10px">Success rate denominator is '
        f'<b>runs recorded</b> ({denom}), not expected days '
        f'({counts["expected_days"]}). Missing days are counted separately and are '
        f"never absorbed into the success rate.</p>"
    )
    if counts["malformed_ledger_rows"]:
        parts.append(
            f'<p class="sub"><b>{counts["malformed_ledger_rows"]}</b> ledger row(s) '
            f"could not be parsed and were excluded from every count above.</p>"
        )

    parts.append(
        f"<h2>Last {counts['expected_days']} UTC days "
        f"({_esc(payload['window']['start'])} → {_esc(payload['window']['end'])})</h2>"
    )
    parts.append("<table><thead><tr>")
    for head in (
        "UTC day",
        "Start",
        "Status",
        "Mode",
        "Seconds",
        "Bronze rows",
        "Gold rows",
        "Commit",
        "Detail",
    ):
        parts.append(f"<th>{_esc(head)}</th>")
    parts.append("</tr></thead><tbody>")
    # Never empty: a day with no run is rendered as an explicit MISSING row,
    # so an idle schedule produces a table full of warnings rather than a
    # short, tidy table that looks fine at a glance.
    parts.append(_rows_html(summary))
    parts.append("</tbody></table>")

    parts.append("<h2>Provenance</h2>")
    parts.append("<dl>")
    prov_rows = [
        ("Generated at (UTC)", _esc(payload["generated_at_utc"])),
        ("Schedule", _esc(fresh["schedule"])),
        ("Newest run (UTC)", _esc(fresh["latest_run_at_utc"] or "—")),
        ("Newest success (UTC)", _esc(fresh["latest_success_at_utc"] or "—")),
        ("Stale after", f'{_esc(fresh["stale_after_hours"])} h'),
        ("Source commit", _link(
            f'{meta.repo_url}/commit/{meta.source_sha}' if meta.repo_url and meta.source_sha != "unknown" else "",
            meta.source_sha,
        ) if meta.source_sha != "unknown" else "unknown"),
        ("Producing workflow run", _link(prov["workflow_run_url"], "open run log")),
        ("Ledger location", _esc(prov["ledger_ref"] or "—")),
        ("Ledger rows read", _esc(counts["ledger_rows_total"])),
        ("Renderer version", _esc(payload["renderer_version"])),
        ("Content SHA-256", _esc(payload["content_sha256"])),
    ]
    for k, v in prov_rows:
        parts.append(f"<dt>{_esc(k)}</dt><dd>{v}</dd>")
    parts.append("</dl>")

    parts.append(
        '<footer>Machine-readable form of this page: '
        '<a href="runs.json">runs.json</a>. '
        "Rendered by <code>evidence/render.py</code>; the ledger it reads is written "
        "by <code>observability/run_log.py</code>.</footer>"
    )

    parts.append("</main>")
    parts.append(f"<script>{_FRESHNESS_JS}</script>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def build_site(
    runs: pd.DataFrame, now: datetime, meta: PageMeta | None = None
) -> dict[str, str]:
    """Pure render: ledger + clock + provenance -> the files to publish.

    Returns a mapping of relative filename to file content. No I/O.
    """
    meta = meta or PageMeta()
    summary = summarize_window(
        runs,
        now,
        window_days=meta.window_days,
        stale_after_hours=meta.stale_after_hours,
    )
    payload = build_payload(summary, now, meta)
    return {
        "index.html": render_html(payload, summary, meta),
        "runs.json": json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _meta_from_env(args: argparse.Namespace) -> PageMeta:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    repo_url = f"{server}/{repo}" if repo else ""
    run_url = f"{repo_url}/actions/runs/{run_id}" if repo_url and run_id else ""
    sha = os.environ.get("GITHUB_SHA", "").strip() or "unknown"
    return PageMeta(
        source_sha=sha,
        run_url=run_url,
        ledger_ref=args.ledger_ref,
        repo_url=repo_url,
        schedule_desc=args.schedule_desc,
        window_days=args.window_days,
        stale_after_hours=args.stale_after_hours,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ledger",
        default="warehouse/run_log.parquet",
        help="path to the run ledger snapshot (its parts directory is authoritative)",
    )
    parser.add_argument("--out", default="site", help="output directory")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument(
        "--stale-after-hours", type=int, default=DEFAULT_STALE_AFTER_HOURS
    )
    parser.add_argument(
        "--ledger-ref",
        default="branch: evidence, path: warehouse/run_log_parts/",
        help="human-readable description of where the ledger is persisted",
    )
    parser.add_argument("--schedule-desc", default="daily, 05:23 UTC")
    parser.add_argument(
        "--fail-on-state",
        default="",
        help="comma-separated states that should exit non-zero (e.g. no-evidence)",
    )
    args = parser.parse_args(argv)

    from observability import run_log  # local import keeps this module import-cheap

    runs = run_log.read_runs(args.ledger)
    now = datetime.now(timezone.utc)
    meta = _meta_from_env(args)
    files = build_site(runs, now, meta)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")

    state = json.loads(files["runs.json"])["state"]
    print(f"rendered {len(files)} file(s) to {out} | state={state}")
    print(
        f"  window={meta.window_days}d observed_days="
        f"{json.loads(files['runs.json'])['counts']['observed_days']}"
    )

    blocking = {s.strip() for s in args.fail_on_state.split(",") if s.strip()}
    if state in blocking:
        print(f"ERROR: evidence state {state!r} is configured to block", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
