"""Pipeline run audit log — durable observability for every orchestrator run.

Every execution of `orchestrate.py` (local, Docker, CI or Dagster) appends
exactly one row to a Parquet audit table under `warehouse/run_log.parquet`.
The table answers the questions an on-call engineer actually asks:

    * when did the pipeline last run, and did it succeed?
    * was it live EVDS data or the synthetic fixture?
    * how long did it take, and is it getting slower?
    * how many bronze/gold rows did that run produce?
    * which commit produced it?

Design notes
------------
* Append-only: a run row is never rewritten, so run history is a time
  series you can trend (duration regressions, row-count drops).
* Failure rows are recorded too — a log that only records successes is
  useless for incident review.
* Parquet (not JSON) so the audit table is queryable from DuckDB with the
  same engine as the marts: `select * from 'warehouse/run_log.parquet'`.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

RUN_LOG_COLUMNS = [
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
]

VALID_STATUS = {"success", "failure"}


@dataclass(frozen=True)
class RunRecord:
    """One immutable audit row describing a single pipeline execution."""

    run_id: str
    started_at_utc: str
    ended_at_utc: str
    duration_seconds: float
    status: str
    mode: str
    source_name: str
    bronze_rows: int
    gold_rows: int
    steps_total: int
    steps_failed: int
    git_sha: str
    failed_step: str = ""

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUS:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUS)}, got {self.status!r}"
            )
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")


def new_run_id() -> str:
    """Return a collision-free identifier for one pipeline execution."""
    return uuid.uuid4().hex


def utc_now() -> str:
    """UTC timestamp, second precision — comparable across machines."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git_sha(root: Path | None = None) -> str:
    """Best-effort commit identity of the code that produced this run.

    CI exports GITHUB_SHA; locally we ask git. If neither is available
    (e.g. a source tarball) we record "unknown" rather than guessing.
    """
    env_sha = os.environ.get("GITHUB_SHA", "").strip()
    if env_sha:
        return env_sha[:40]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root or Path.cwd()),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()[:40]
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})


def read_runs(path: str | Path) -> pd.DataFrame:
    """Read the audit table; an absent log is an empty log, not an error."""
    p = Path(path)
    if not p.exists():
        return _empty_frame()
    df = pd.read_parquet(p)
    missing = [c for c in RUN_LOG_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"run log at {p} is missing columns: {missing}")
    return df[RUN_LOG_COLUMNS]


def append_run(path: str | Path, record: RunRecord) -> Path:
    """Append one run row to the Parquet audit table and return its path.

    Read-modify-write is deliberate: the log is small (one row per run,
    weekly cadence) and the pipeline is single-writer, so the simplicity
    of one self-describing Parquet file beats a partitioned layout here.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = read_runs(p)
    row = pd.DataFrame([asdict(record)])[RUN_LOG_COLUMNS]
    combined = row if existing.empty else pd.concat([existing, row], ignore_index=True)
    combined.to_parquet(p, index=False)
    return p


def summarize(path: str | Path, last: int = 5) -> str:
    """Human-readable tail of the audit table for CI/console output."""
    df = read_runs(path)
    if df.empty:
        return "run_log: empty"
    tail = df.tail(last)
    lines = [
        f"{r.started_at_utc} | {r.status:<7} | {r.mode:<7} | "
        f"{float(r.duration_seconds):6.1f}s | gold_rows={r.gold_rows} | {str(r.git_sha)[:7]}"
        for r in tail.itertuples()
    ]
    return "\n".join(lines)
