# Observability — pipeline run audit log (M12, hardened in M13)

## Problem

Until M11 the pipeline's history lived only in GitHub Actions console logs:
ephemeral, unqueryable, and gone once a run is rotated out. There was no way
to answer "when did this last succeed?", "is it getting slower?" or "which
commit produced today's gold table?" without opening a browser.

## Solution

`observability/run_log.py` records **one row per orchestrator execution** in
an append-only Parquet ledger under `warehouse/`.

### Storage layout

```text
warehouse/run_log_parts/run-<run_id>-<digest>.parquet   source of truth
warehouse/run_log.parquet                               derived snapshot
```

Each run writes its **own** part file and reads no other run's data in order
to record its own. Every write lands on a temporary file in the destination
directory and is then moved into place with `os.replace`, which is atomic, so
a reader sees either the old file or the complete new one — never a
half-written Parquet footer. Temporary files are hidden and are not suffixed
`.parquet`, so an in-flight write is invisible to the `*.parquet` glob and to
a DuckDB directory scan.

`warehouse/run_log.parquet` is kept as a **derived** snapshot so the
documented DuckDB one-liner and the CI artifact contract keep working
unchanged. It is rebuilt on every append and can be regenerated at any time
with `compact()`; deleting it loses nothing, because the parts are the
ledger.

### Schema

| column | type | meaning |
|---|---|---|
| `run_id` | str | UUID4 hex, unique per execution |
| `started_at_utc` | str | ISO-8601 UTC, second precision |
| `ended_at_utc` | str | ISO-8601 UTC, second precision |
| `duration_seconds` | float | wall-clock, monotonic-clock derived |
| `status` | str | `success` \| `failure` (validated) |
| `mode` | str | `live` \| `fixture` |
| `source_name` | str | e.g. `evds:TP.FG.J0`, `fixture:synthetic` |
| `bronze_rows` | int | rows in the bronze lake after ingest |
| `gold_rows` | int | rows in `mart_inflation_yoy` |
| `steps_total` | int | orchestrator steps attempted |
| `steps_failed` | int | orchestrator steps that failed |
| `git_sha` | str | `GITHUB_SHA`, else `git rev-parse HEAD`, else `unknown` |
| `failed_step` | str | name of the first failing step (empty on success) |

## Design decisions

1. **Append-only.** Rows are never rewritten, so the log is a time series you
   can trend — duration regressions and row-count drops become visible.
2. **Failures are recorded.** A log that only stores successes is useless for
   incident review; the failure path writes its row from an exception handler.
3. **Parquet, not JSON.** The audit table is queryable by the same DuckDB
   engine that serves the marts — no second tool to learn.
4. **One file per run, not one file per ledger.** M12 appended by reading the
   whole Parquet file, concatenating a row and writing it back. That
   read-modify-write loses a run whenever two executions overlap between the
   read and the write: the second writer's snapshot never contained the
   first writer's row, so the first run was silently erased. An audit log
   that can quietly drop the record of a run is worse than none, because it
   is trusted. M13 replaced it with per-run part files plus atomic renames,
   and the failure it fixes is now reproduced deterministically in the test
   suite rather than described in prose.
5. **Re-recording a run is safe.** A retried write targets the same part
   filename, so it overwrites that run's own row and the ledger stays at one
   row per `run_id`. Retries cannot duplicate history.
6. **Observability must not create a new failure mode.** The audit write is
   wrapped defensively — if it fails, it warns and leaves the pipeline's own
   exit code untouched. The snapshot refresh is likewise best-effort: the run
   is already durable in its part file before the snapshot is touched.

## Querying

```sql
-- last 10 runs (derived snapshot: the convenient path)
select started_at_utc, status, mode, duration_seconds, gold_rows, git_sha
from 'warehouse/run_log.parquet'
order by started_at_utc desc
limit 10;

-- the same history straight from the source of truth
select status, count(*) as runs
from 'warehouse/run_log_parts/*.parquet'
group by 1;

-- success rate and median duration by mode
select mode,
       count(*) as runs,
       avg(case when status = 'success' then 1.0 else 0.0 end) as success_rate,
       median(duration_seconds) as p50_seconds
from 'warehouse/run_log.parquet'
group by mode;
```

From Python:

```python
from observability.run_log import compact, read_runs, summarize

print(summarize("warehouse/run_log.parquet", last=5))
df = read_runs("warehouse/run_log.parquet")   # parts + snapshot, deduplicated
compact("warehouse/run_log.parquet")          # rebuild the snapshot if needed
```

`read_runs` treats the parts directory as authoritative and reads the
snapshot only for `run_id`s that have no part file. That is what carries
pre-M13 history — and any history restored from a CI artifact — forward
without duplicating current rows.

## Verification

* `tests/test_run_log.py` — contract checks (schema stability, append-only
  history, failure capture, invariant rejection, DuckDB readability). These
  pass **unchanged** against the M13 layout; the storage change is not a
  contract change.
* `tests/test_run_log_concurrency.py` — self-checking proofs in five parts: a
  deterministic replay of the M12 lost update, the identical interleaving
  driven through the current API, pre-M13 history migration, retry
  idempotency, and **12 real OS processes** released on a shared barrier
  against one ledger, after which every run must still be present and the
  derived snapshot must agree with the parts.
* `.github/workflows/run-audit.yml` — runs all three test modules, then
  executes the real pipeline twice in fixture mode and reads the result back
  with DuckDB from both the snapshot and the `run_log_parts/*.parquet` glob,
  asserting that no `run_id` appears twice, that the schema contract holds,
  and that the snapshot row count equals the parts row count. The parts
  directory is uploaded with the evidence artifact, so the artifact contains
  the source of truth and not only the snapshot.

## Known limitations

* `warehouse/` is git-ignored, so the ledger is per-environment. Durable
  cross-run history requires persisting it to the S3/MinIO lake — still out
  of scope, and therefore no cross-environment history is claimed.
* Concurrency safety rests on `os.replace` being atomic within one
  filesystem. That holds for a local disk and for the CI runner; it is not
  guaranteed on every network filesystem, so a shared NFS mount is not a
  supported deployment target.
* The derived snapshot can lag the parts by one run if a process dies between
  the part write and the refresh. Readers that use `read_runs` never see the
  lag; a direct `select * from 'warehouse/run_log.parquet'` can, until the
  next append or an explicit `compact()`.
