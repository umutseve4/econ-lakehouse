# Observability — pipeline run audit log (M12)

## Problem

Until M11 the pipeline's history lived only in GitHub Actions console logs:
ephemeral, unqueryable, and gone once a run is rotated out. There was no way
to answer "when did this last succeed?", "is it getting slower?" or "which
commit produced today's gold table?" without opening a browser.

## Solution

`observability/run_log.py` appends **one row per orchestrator execution** to
an append-only Parquet table at `warehouse/run_log.parquet`.

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
4. **Read-modify-write is intentional.** One row per weekly run, single
   writer: a flat self-describing file beats a partitioned layout at this
   scale. If cadence ever goes sub-hourly, partition by month.
5. **Observability must not create a new failure mode.** The audit write is
   wrapped defensively — if it fails, it warns and leaves the pipeline's own
   exit code untouched.

## Querying

```sql
-- last 10 runs
select started_at_utc, status, mode, duration_seconds, gold_rows, git_sha
from 'warehouse/run_log.parquet'
order by started_at_utc desc
limit 10;

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
from observability.run_log import read_runs, summarize

print(summarize("warehouse/run_log.parquet", last=5))
df = read_runs("warehouse/run_log.parquet")
```

## Verification

* `tests/test_run_log.py` — 19 contract checks (schema stability, append-only
  history, failure capture, invariant rejection, DuckDB readability).
* `.github/workflows/run-audit.yml` — runs those tests, then executes the real
  pipeline twice in fixture mode and asserts the log grew to exactly two rows
  with two distinct `run_id`s and non-zero `gold_rows`.

## Known limitations

* Single-writer only: concurrent orchestrator runs against the same path can
  lose a row (read-modify-write is not atomic). Acceptable for a weekly
  scheduled pipeline; would need a partitioned layout otherwise.
* `warehouse/` is git-ignored, so the log is per-environment. Durable
  cross-run history requires persisting it to the S3/MinIO lake — deliberately
  out of scope for M12.
