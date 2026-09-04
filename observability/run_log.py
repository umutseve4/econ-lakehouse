"""Pipeline run audit log — durable observability for every orchestrator run.

Every execution of `orchestrate.py` (local, Docker, CI or Dagster) records
exactly one row in a Parquet audit ledger under `warehouse/`. The ledger
answers the questions an on-call engineer actually asks:

    * when did the pipeline last run, and did it succeed?
    * was it live EVDS data or the synthetic fixture?
    * how long did it take, and is it getting slower?
    * how many bronze/gold rows did that run produce?
    * which commit produced it?

Storage layout (M13)
--------------------
The ledger is a **part directory plus a derived snapshot**, not a single
mutable file:

    warehouse/run_log_parts/run-<run_id>-<digest>.parquet   <- source of truth
    warehouse/run_log.parquet                               <- derived snapshot

Each run writes its *own* part file, so two runs never write the same
object and no run has to read another run's data in order to record its
own. Every write goes to a temporary file in the destination directory
and is then moved into place with `os.replace`, which is atomic on POSIX
and on Windows — a reader therefore sees either the old file or the
complete new one, never a half-written Parquet footer.

`warehouse/run_log.parquet` is kept as a *derived* convenience snapshot so
that the documented one-liner `select * from 'warehouse/run_log.parquet'`
and the CI artifact contract keep working unchanged. It is rebuilt from
the parts on every append and is always safe to delete or regenerate with
`compact()`. Losing it loses nothing: the parts are the ledger.

Why this replaces the previous read-modify-write append
-------------------------------------------------------
The earlier implementation read the whole Parquet file, concatenated one
row, and wrote the file back. Two runs overlapping anywhere between the
read and the write produced a classic lost update: the second writer's
snapshot did not contain the first writer's row, and the first row was
silently erased. An audit log that can silently drop the record of a run
is worse than no audit log, because it is trusted. `tests/
test_run_log_concurrency.py` reproduces that loss deterministically
against the old algorithm and proves this layout does not lose the row.

Design notes
------------
* Append-only: a run row is never rewritten, so run history is a time
  series you can trend (duration regressions, row-count drops).
* Failure rows are recorded too — a log that only records successes is
  useless for incident review.
* Parquet (not JSON) so the audit table is queryable from DuckDB with the
  same engine as the marts.
* Re-recording the same `run_id` overwrites that run's own part and stays
  one row, so a retried write cannot duplicate history.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_log = logging.getLogger(__name__)

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

PARTS_SUFFIX = "_parts"

_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


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
        if not str(self.run_id).strip():
            raise ValueError("run_id must not be empty")


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


def parts_dir(path: str | Path) -> Path:
    """Directory holding the per-run part files for a given snapshot path."""
    p = Path(path)
    return p.parent / f"{p.stem}{PARTS_SUFFIX}"


def _part_name(run_id: str) -> str:
    """Filesystem-safe, collision-free part filename for one run_id.

    The sanitised id keeps the file readable during an incident; the
    digest of the *raw* id guarantees that two different run_ids can
    never sanitise onto the same filename.
    """
    safe = _UNSAFE_IN_FILENAME.sub("-", str(run_id))[:64]
    digest = hashlib.sha1(str(run_id).encode("utf-8")).hexdigest()[:12]
    return f"run-{safe}-{digest}.parquet"


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in RUN_LOG_COLUMNS})


def _atomic_write_parquet(df: pd.DataFrame, dest: Path) -> Path:
    """Write `df` so that readers only ever see a complete file.

    The temporary file is created in the destination directory (a rename
    across filesystems is not atomic) and is hidden and non-`.parquet`
    suffixed so that in-flight writes are never picked up by the
    `*.parquet` glob or by a DuckDB directory scan.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, dest)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return dest


def _read_frame(p: Path) -> pd.DataFrame:
    df = pd.read_parquet(p)
    missing = [c for c in RUN_LOG_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"run log at {p} is missing columns: {missing}")
    return df[RUN_LOG_COLUMNS]


def read_runs(path: str | Path) -> pd.DataFrame:
    """Read the audit ledger; an absent ledger is an empty ledger, not an error.

    The parts directory is authoritative. The derived snapshot is read too,
    but only for `run_id`s that have no part file — that is what preserves
    history written by the pre-M13 single-file implementation (and any
    history restored from a CI artifact) without duplicating current rows.
    """
    p = Path(path)
    frames: list[pd.DataFrame] = []
    part_ids: set[str] = set()

    d = parts_dir(p)
    if d.is_dir():
        for f in sorted(d.glob("*.parquet")):
            try:
                mtime = f.stat().st_mtime_ns
            except OSError:  # pragma: no cover - vanished between glob and stat
                continue
            df = _read_frame(f).copy()
            if df.empty:
                continue
            df["_src"] = 1
            df["_ord"] = mtime
            df["_name"] = f.name
            frames.append(df)
            part_ids.update(df["run_id"].astype(str))

    if p.is_file():
        snapshot = _read_frame(p)
        legacy = snapshot[~snapshot["run_id"].astype(str).isin(part_ids)].copy()
        if not legacy.empty:
            legacy["_src"] = 0
            legacy["_ord"] = range(len(legacy))
            legacy["_name"] = ""
            frames.append(legacy)

    if not frames:
        return _empty_frame()

    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["run_id"], keep="first")
    out = out.sort_values(
        by=["started_at_utc", "_src", "_ord", "_name"], kind="stable"
    )
    return out[RUN_LOG_COLUMNS].reset_index(drop=True)


def write_part(path: str | Path, record: RunRecord) -> Path:
    """Durably record one run as its own part file and return that file.

    This is the only write that matters. It touches no other run's data,
    so concurrent runs cannot overwrite each other. Exposed separately
    from `append_run` so tests can interleave writes explicitly.
    """
    row = pd.DataFrame([asdict(record)])[RUN_LOG_COLUMNS]
    return _atomic_write_parquet(row, parts_dir(path) / _part_name(record.run_id))


def compact(path: str | Path) -> Path:
    """Rebuild the derived snapshot at `path` from the parts directory."""
    p = Path(path)
    return _atomic_write_parquet(read_runs(p), p)


def append_run(path: str | Path, record: RunRecord) -> Path:
    """Record one run, then refresh the derived snapshot; return the snapshot path.

    The part write is the durable one. The snapshot refresh is a
    convenience for the documented DuckDB one-liner and the CI artifact,
    so a snapshot failure is logged and swallowed: the run is already
    recorded, and `compact()` can rebuild the snapshot at any time.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_part(p, record)
    try:
        compact(p)
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning(
            "run log snapshot refresh failed (run is still recorded in %s): %s",
            parts_dir(p),
            exc,
        )
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
