<h1 align="center">econ-lakehouse</h1>

<p align="center">
  A tested medallion warehouse for Turkish macroeconomic data —<br>
  and, more unusually, one that <b>tells you when its own numbers are stale</b><br>
  instead of quietly swapping in a series that looks fresher.
</p>

<p align="center">
  <a href="https://umutseve4.github.io/econ-lakehouse/"><b>▶ Open the live evidence page</b></a>
  &nbsp;·&nbsp; static, self-checking, nothing to wake up
</p>

<p align="center">
  <a href="https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml"><img src="https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml/badge.svg" alt="pipeline"></a>
  <a href="https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml"><img src="https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml/badge.svg" alt="freshness-gate"></a>
  <a href="https://github.com/umutseve4/econ-lakehouse/actions/workflows/run-audit.yml"><img src="https://github.com/umutseve4/econ-lakehouse/actions/workflows/run-audit.yml/badge.svg" alt="run-audit"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/freshness%20checks-73-FF4D4F?style=flat-square" alt="73 freshness checks">
  <img src="https://img.shields.io/badge/concurrent%20writers%20proven-12-FF4D4F?style=flat-square" alt="12 concurrent writers">
  <img src="https://img.shields.io/badge/candidate%20series%20rejected-14-FF4D4F?style=flat-square" alt="14 candidate series rejected">
</p>

---

## Audit 001: is the Turkish CPI gap an arithmetic error?

For August 2026 the official institute (TUIK) published **31.51%** annual CPI
inflation. The independent group (ENAG) published **49.03%** for the same month.
A common claim on both sides is that the other one cannot even add up correctly.

This repository now contains an audit that tests exactly that claim, applying one
identical test to both institutions.

| | internal arithmetic test | reproducibility scorecard |
|---|---|---|
| **TUIK** | PASS, 64 of 64 months clean | 8/8 |
| **ENAG** | PASS, uses 17.9% of the rounding envelope | 2/8 |

**Neither side has an arithmetic error.** The 17.5 point gap does not come from
addition. It comes from the basket, the weights and the price collection method.
The real asymmetry is not accuracy but auditability: a third party can rebuild the
TUIK figure end to end and cannot rebuild the ENAG one.

```bash
python audits/001-tufe-aritmetigi/audit.py --check
```

No dependencies, standard library only. Every number in the report is recomputed
from the raw CSV; if one drifts, the exit code is 1 and CI turns red.

- **[Read the audit](audits/001-tufe-aritmetigi/README.md)** (in Turkish)
- [Pre-registered protocol](audits/001-tufe-aritmetigi/PROTOCOL.md), committed in
  its own earlier commit; the ordering is asserted from git history by a test
- [Appendix A](audits/001-tufe-aritmetigi/EK-A-artik-tablosu.md), the full 64 row
  residual table, regenerated and byte-compared by CI on every run
- [Sources](audits/001-tufe-aritmetigi/data/SOURCES.md), one code per data cell

The report also carries its own error log. The first published version named the
wrong month for the largest residual. That version **failed CI** at commit
`f55ca86`, the correction passed at `55a2beb`, and both states remain in history.
The guard was proved by a real break, not by a claim.

---

## Run the whole thing in four commands

```bash
pip install -r requirements.txt
python tests/test_ingest.py
python tests/test_freshness.py
python orchestrate.py
```

The single entrypoint performs fetch → bronze ingest → idempotency proof → dbt
build → gold sanity check and exits non-zero on failure. It turns API/CSV input
into validated bronze Parquet, typed dbt silver models, analytical gold marts, a
read-only API, and a Streamlit dashboard.

Use official EVDS input only through an environment variable; never place the key
in a URL, source file, log, or commit:

```bash
EVDS_API_KEY=... python orchestrate.py
```

## The path, made explicit

Analytical SQL written directly against raw files is untyped, unvalidated, and
difficult to reproduce. This project makes the full path explicit and testable:

```text
TCMB EVDS / synthetic CI fixture
        │  schema contract + idempotent ingest
        ▼
Bronze Parquet (partitioned, append-safe, provenance stamped)
        │  dbt + DuckDB
        ▼
Silver typed/deduplicated views
        │  dbt tests
        ▼
Gold mart_inflation_yoy
        ├── FastAPI (read-only, parameterized)
        └── Streamlit dashboard (provenance + freshness visible)

Each orchestrated run
        └── warehouse/run_log_parts/ (one atomic part file per run)
                └── warehouse/run_log.parquet (derived snapshot)
```

| Layer | Main tools | Enforced checks |
|---|---|---|
| Bronze | pandas, pyarrow, fsspec | schema, ISO dates, positive values, no duplicate `(date, item_code)`, provenance, idempotent upsert |
| Silver | dbt, DuckDB | typing, `not_null`, uniqueness, positivity, latest-fetch deduplication |
| Gold | dbt table | non-null YoY metric, non-empty mart, revision history |
| Serving | FastAPI, Streamlit | read-only DB, parameterized SQL, response limits, provenance and freshness disclosure |
| Operations | GitHub Actions, Docker, Dagster, Parquet audit log | clean rebuilds, remote-storage smoke, scheduled alerting, live freshness gate, one atomically written run record per orchestration attempt, proven against 12 concurrent writers |

## Current status notices

> **Freshness notice (verified 2026-08-22):** the official production source
> `TP.FG.J0` currently ends at **2026-01**. The warehouse is live-source, but its
> newest CPI observation is not current. The dashboard is designed to display the
> exact observation date and lag instead of presenting the value as current. See
> [Data freshness policy](docs/data-freshness.md).

> **Deployment evidence boundary (re-verified 2026-09-04T22:25Z):** the Streamlit
> Community Cloud application at
> [econ-lakehouse-umut.streamlit.app](https://econ-lakehouse-umut.streamlit.app/)
> is currently **dormant**. The URL returns "This app has gone to sleep due to
> inactivity" instead of the dashboard, so the deployed commit SHA cannot be
> verified while it sleeps. The link is retained for portfolio access and wakes on
> click, but no always-on availability is claimed and deployment is tracked
> separately from code and CI evidence.

> **Evidence page (verified live 2026-09-06):** the static page at
> [umutseve4.github.io/econ-lakehouse](https://umutseve4.github.io/econ-lakehouse/)
> is published and serving. Its most recent render was generated at
> **2026-09-05T00:40:31Z** from **2 recorded runs**, and it displays the other
> **12 days of the 14-day window as explicit `MISSING` rows**. Until 2026-09-06
> this README said the page was "implemented, not yet published" because Pages was
> disabled; that sentence was stale and is corrected below.

## Data freshness: an explicit limitation, not a silent series swap

The production mapping remains `TP.FG.J0 → CP00`. Live diagnostics proved that
extending `endDate`, removing aggregation/formula parameters, and requesting the
bare series all return the same non-null tail ending at **2026-01**. The freeze is
upstream, not a parser or dbt defect.

A sweep tested **14 candidate series**. No series was both current and
historically compatible. `TP.TUFE1YI.T1` reaches **2026-07**, but across
**121 overlapping YoY months** its mean absolute difference from `TP.FG.J0` is
**15.1540 percentage points** and its maximum difference is
**72.1737 percentage points at 2022-10**. A simple index rebasing cannot cause
that: the constant base factor cancels in the YoY ratio.

Therefore this repository does **not** splice a different methodology onto the
old history. The implemented policy is:

- **0–3 calendar months:** fresh/pass.
- **4+ calendar months:** stale/fail.
- Dashboard: exact newest date, exact month lag, and prominent stale warning.
- Every PR/push: deterministic `3`-month-pass and `4`-month-fail tests.
- Weekly/manual live run: fetch `TP.FG.J0`, fail beyond **3 months**, and open one deduplicated `data-freshness` issue, or comment on it if it is already open.
- Future migration: require authoritative series metadata and full-history compatibility evidence, then rebuild the whole history and document the methodology break.

Because the freeze is known, investigated and permanent, the weekly gate would
otherwise be red forever — and a check that can only ever be red carries no
information. CI therefore recognises one **time-boxed acknowledgement**
(`ingest/freshness_waiver.py`, expiring **2026-10-05**, exclusive) that classifies
this exact series at this exact frozen month as `acknowledged_stale` rather than a
new failure. It is **CI-only**: `quality/freshness.py` is unchanged, so the
dashboard still reports the freeze as an error to human readers. Any change in
series, month or date makes the gate red again with no human action. Details and
renewal rules: [docs/data-freshness.md](docs/data-freshness.md).

## Surfaces

<details>
<summary><b>Docker</b></summary>

```bash
docker build -t econ-lakehouse .
docker run --rm econ-lakehouse

docker run --rm -e EVDS_API_KEY=... econ-lakehouse
```

</details>

<details>
<summary><b>API</b></summary>

```bash
uvicorn serve.app:app --port 8000
curl http://localhost:8000/health
curl 'http://localhost:8000/v1/inflation?year=2024&limit=5'
curl http://localhost:8000/v1/inflation/latest
```

The API opens DuckDB with `read_only=True`, uses parameterized filters, and caps
`limit` at **1000**. OpenAPI documentation is available at `/docs`. Set
`LAKE_DB=/path/to.duckdb` to use another warehouse.

</details>

<details>
<summary><b>Dashboard</b></summary>

```bash
streamlit run dashboard/app.py
```

The Streamlit app shows latest available YoY observations, an interactive time
series, raw data, and CSV export. Data access is isolated in `dashboard/data.py`;
freshness policy is pure/testable in `quality/freshness.py`. On cold start,
`dashboard/bootstrap.py` invokes the same `orchestrate.py` pipeline used by CI and
Docker. `warehouse/provenance.json` records fixture/live mode, source, UTC build
time, and gold row count.

</details>

<details>
<summary><b>Dagster</b></summary>

```bash
pip install dagster dagster-webserver
dagster dev -f orchestration/definitions.py
```

The asset graph is `bronze_cpi → warehouse_marts` plus a `gold_nonempty` asset
check. CI materializes it in-process; Dagster adds lineage, retries, scheduling,
and observability without creating a second pipeline implementation.

</details>

## Data and storage

`data/sample/cpi_fixture.csv` is synthetic and exists only for deterministic
testing. It is **not** official statistics. Live mode uses TCMB EVDS. Bronze data
can also target S3-compatible storage through an fsspec URI; CI verifies the path
against a real MinIO service. dbt snapshots retain SCD Type 2 revision history
when upstream values change.

## CI and alerting

The main workflow rebuilds and verifies ingestion, dbt models/tests, idempotency,
API, dashboard, Dagster, Docker, and S3-compatible storage. It runs weekly at
`17 6 * * 1`. A scheduled failure opens one `pipeline-failure` issue and records
every later failure as a comment on that same issue, deduplicating on a stable
HTML marker rather than on the issue title. Until 2026-09-04 this sentence was
inaccurate: the job put the run date *in* the title and performed no lookup at
all, so a recurring failure would have opened a new issue every Monday. Neither
branch of the corrected logic has yet been observed firing in production — see
issue #47.

The independent freshness workflow runs deterministic policy tests on code changes
and the live gate weekly at `47 6 * * 1` or on manual dispatch. Keeping the live
upstream check separate prevents a known external freeze from making unrelated
pull requests unmergeable while still producing an operational failure signal.

The independent run-audit workflow runs the contract, failure-path, and
concurrency test modules, executes the fixture pipeline twice, then reads the
result back with DuckDB from both the derived snapshot and the
`run_log_parts/*.parquet` glob — asserting that no `run_id` appears twice, that
the schema contract holds, and that the snapshot row count equals the parts row
count. Both the snapshot and the parts directory are uploaded as the audit
artifact.

The evidence workflow runs daily at `23 5 * * *` and on manual dispatch. It
restores the run ledger from the `evidence` branch, executes the fixture pipeline,
appends this run's part file back to that branch, renders a static status page
from the ledger, and publishes it. A failed pipeline run is still recorded and
still published — the page shows `FAILING` — and the workflow reports failure only
afterwards, so a broken pipeline can never produce a green run *and* a silent
page. On pull requests the workflow only tests the renderer: it never writes to
the ledger branch and never deploys.

## Run observability

Every `orchestrate.py` attempt writes one append-only record without changing the
pipeline's original exit semantics. The record includes run identity and timing,
success/failure state, mode and source, bronze/gold row counts, step totals,
failed step, and Git SHA. Query examples, the schema contract, and CI evidence are
documented in [docs/observability.md](docs/observability.md).

Each run writes its **own** part file under `warehouse/run_log_parts/` through a
temporary file and an atomic `os.replace`, so no run reads or rewrites another
run's data. `warehouse/run_log.parquet` is a derived snapshot rebuilt from those
parts, kept so the documented DuckDB one-liner and the CI artifact contract are
unchanged; it can be regenerated at any time with `compact()`.

This replaces the earlier read-modify-write append, which lost a run whenever two
executions overlapped between the read and the write. That loss is now reproduced
deterministically against the old algorithm in
`tests/test_run_log_concurrency.py`, and the same interleaving — plus 12 genuinely
concurrent OS processes — is proved to lose nothing under the current layout.
Since M14 the ledger is no longer purely per-environment: the scheduled evidence
workflow persists each run's part file to a dedicated orphan `evidence` branch and
refuses any commit that modifies or deletes an existing part, so the recorded
history is append-only in git as well as on disk. Remaining honest limitation:
this is durability inside one GitHub repository, not the S3/MinIO lake, and a
local or Codespace run still keeps its ledger only in the git-ignored `warehouse/`
directory. Production-ready is therefore still not claimed.

## Published evidence page

**Live at [umutseve4.github.io/econ-lakehouse](https://umutseve4.github.io/econ-lakehouse/).**

The dashboard is deployed on Streamlit Community Cloud, which suspends an app
after inactivity. A reviewer opening that link is shown a wake-up screen rather
than evidence, so availability there cannot be claimed.

M14 adds a second, deliberately dumber surface: a static page generated from the
run ledger by `evidence/render.py` and served from GitHub Pages. It has nothing to
wake up. Because a static page can just as easily keep serving a cheerful result
after the schedule feeding it has stopped, the page is built to fail closed:

- It carries its own `generated at`, `latest run` and staleness threshold as data attributes, and re-evaluates its age in the reader's browser on load — so it turns itself `STALE` without any server. With JavaScript disabled it says freshness was not verified instead of implying it was.
- Age overrides success. A run window that is entirely green but older than 30 hours renders `STALE`, not `HEALTHY`.
- Days with no run are shown as explicit `MISSING` rows rather than omitted, so an empty stretch looks empty. An empty or wholly unparseable ledger renders `NO EVIDENCE` and exits non-zero; it cannot render a tidy page.
- Rows that fail to parse are counted and displayed, never silently dropped, and the success-rate denominator is the number of *recorded runs* — stated on the page — not the number of days expected.
- The page labels its own data mode (`SYNTHETIC FIXTURE`) and lists what it does and does not prove. The words `real-time`, `production-ready`, `uptime`, `always-on` and `24/7` are rejected by the test suite.

`tests/test_evidence_render.py` covers the UTC day boundaries, the window edges,
the strict staleness cut-off, malformed and missing columns, naive and offset
timestamps, HTML escaping, JSON/HTML agreement, and byte-level determinism of the
rendered payload.

The published render carries its own provenance in the page footer: renderer
version **1.0.0**, source commit `99c14827726016bb13a4c27adddf6cd92e5e957f`,
ledger location `branch: evidence, path: run_log_parts/`, **2** ledger rows read,
and a content SHA-256 of the rendered payload. Because the fail-closed rule is
real rather than decorative, the page will present itself as `STALE` to any reader
who opens it more than **30 hours** after that render, regardless of the fact that
both recorded runs succeeded. That is the intended behaviour, and it is the reason
the page is worth publishing at all.

## Evidence status

<details>
<summary><b>Full evidence ledger — including the failures</b></summary>

- Ingest: **tested** — **12/12** unit tests plus end-to-end pipeline.
- Serving API: **tested** — **13** fixture-based tests, including SQL injection and limit validation.
- Dashboard: **tested** — **11** data/UI tests with a headless Streamlit `AppTest` render.
- Bootstrap/provenance: **tested** — **8** stubbed tests plus fixture-mode end-to-end build.
- Freshness policy: **tested** — **73** offline checks covering the **3 months = pass** / **4 months = fail** boundary, CSV-tail detection, the production CLI itself, and the time-boxed acknowledgement layer. Most of them are negative: they prove the acknowledgement does *not* apply to the wrong series, a missing series, a moved month, or an expired date. The suite is **mutation-verified** — pulling `review_by` back, advancing `frozen_at`, and dropping `--series` from the CLI were each applied and each turned the suite red (12, 15 and 4 checks respectively) before being reverted.
- Acknowledgement isolation: **tested statically** — the suite reads `quality/freshness.py` and every `dashboard/*.py` and fails if the waiver is referenced there, so the dashboard cannot start agreeing with CI by accident.
- Run audit: **implemented and PR-tested** — append-only Parquet history, success/failure paths, independent DuckDB read, and artifact contract.
- Concurrent-write durability: **tested** — the previous read-modify-write append is replayed through the exact interleaving that silently erased a run, and the current per-part layout is proved to keep every row through that same interleaving, through pre-M13 history migration, through retried writes, and through **12 parallel OS processes** writing to one ledger. Cross-environment durability (persisting the ledger to S3/MinIO) is still **not** implemented.
- PR #14: **merged** — squash merge SHA `b4bbc875fc32ba075fa00fff20b5a4a0659f0900`; that SHA was verified as `main` HEAD during closure.
- Post-merge `main` CI: **verified 2026-09-05T00:05Z** at `main` HEAD `a1a68138d8197a92f7eb53b82383072f65cb10c4` (`M14: durable run ledger… (#48)`). On that exact SHA `pipeline` run **#127** succeeded on all five build jobs, `freshness-gate` run **#95** succeeded, and `evidence` run **#3** succeeded with `publish` correctly skipped. PR-head checks are still not treated as merge-commit checks, which is why this is re-read on the merge commit itself each time.
- Observed CI flake: **recorded, not explained** — on the immediately preceding `main` commit `3c4cf7c0d0fede2b66dc440b99671d909247b4e7`, `pipeline` run **#125** failed in `docker-smoke` alone (exit code 1) while the other four jobs passed. The identical tree passed `docker-smoke` on the pull-request head **#123** and on the next `main` commit **#127**, so the failure did not reproduce. It is listed here rather than omitted, because quoting only the two green runs on either side of a red one would misrepresent the record. Root cause is unknown; if it recurs it should be investigated as a real defect rather than re-labelled flaky.
- Freshness issue deduplication: **corrected, operationally unverified** — the original job deduplicated on the issue title and only ever *created* issues, so once one was open every subsequent weekly failure produced no issue, no comment and no notification at all. It now dedupes on a stable HTML marker and comments on the existing issue with the run URL. A two-run manual proof is still required; tracked in issue #47.
- Pipeline failure alerting: **corrected, operationally unverified** — this README claimed the scheduled `pipeline` workflow opened a *deduplicated* `pipeline-failure` issue, but no deduplication existed: the alert job put the run date in the issue title and never queried existing issues, so a recurring failure would have produced one new issue per week. This is the mirror image of the freshness defect above — one alert deduplicated so aggressively that recurrences were silent, the other not at all. Both now key on a stable HTML marker and record recurrences as comments. Neither the create path nor the comment path has been observed in production; tracked in issue #47.
- Workflow token scope: **tested in CI** — `pipeline.yml` had no top-level `permissions:` block, so `dashboard-smoke`, `docker-smoke`, `remote-storage` and `dagster-orchestration` inherited the repository default token scope. It now declares `permissions: contents: read` at the top level, with `pull-requests: write` and `issues: write` kept only on the two jobs that need them. Because same-repo `pull_request` events run the workflow file from the PR head, the reduced scope was actually executed by CI on the pull request before merge, not merely reviewed.
- Waiver authorization: **not enforced** — any pull request can add an entry to `ingest/freshness_waiver.py` and thereby silence the freshness gate for a chosen series. The tests constrain what a waiver may *say*, not who may add one. Closing this needs branch protection plus a CODEOWNERS rule on that file, which is repository-settings work and is not done.
- Deployment: **verified dormant 2026-09-04T22:25Z** — `econ-lakehouse-umut.streamlit.app` serves the Streamlit Community Cloud inactivity sleep page, so the dashboard is not reachable without a manual wake and the deployed SHA is unverifiable. Always-on availability is **not claimed**; the evidence page that cannot sleep is published and tracked separately below.
- Evidence page renderer: **tested** — **34** tests covering window arithmetic, the fail-closed state hierarchy, malformed input, escaping, and deterministic output.
- Evidence page publication: **published and verified 2026-09-06** — GitHub Pages is enabled and <https://umutseve4.github.io/econ-lakehouse/> serves the rendered ledger. The served page was fetched and read end to end: renderer **1.0.0**, generated at **2026-09-05T00:40:31Z**, source commit `99c1482`, **2** ledger rows read, window **2026-08-23 → 2026-09-05**. This entry previously read "implemented, not yet published — GitHub Pages is disabled for this repository", which stopped being true once Pages was enabled and the deploy job ran; it is corrected here rather than quietly overwritten. Still **not** done: the post-deploy smoke test that matches the served bytes against the source commit is not automated, so byte-for-byte agreement between the published page and the producing commit remains a manual check.
- Scheduled-run evidence: **2 runs recorded, consecutive-day evidence not yet accumulated** — the ledger holds successful runs on **2026-09-04** (23:51:11Z) and **2026-09-05** (00:40:24Z), a **2/14** day coverage, with the remaining **12** days rendered as explicit `MISSING` rows. Two runs 49 minutes apart across a UTC midnight is not a demonstrated daily schedule, and the page does not present it as one. A sustained multi-week record is claimed only once it exists in the ledger.
- Production-ready: **not claimed**.

</details>

<details>
<summary><b>Milestones M1–M14</b></summary>

1. **M1 — vertical slice:** fixture → bronze → silver → gold, quality-gated.
2. **M2 — real source:** EVDS 3 ingestion verified in CI.
3. **M3 — incremental:** provenance and idempotent upsert.
4. **M4 — operations:** Docker, single entrypoint, schedule, failure issue.
5. **M5 — durability:** S3-compatible bronze and SCD Type 2 revisions.
6. **M6 — serving:** read-only FastAPI with tested filters.
7. **M7 — orchestration:** Dagster assets, check, job, schedule.
8. **M8 — dashboard:** isolated query layer and headless UI test.
9. **M9 — cloud deploy:** self-bootstrapping Streamlit deployment implementation.
10. **M10 — provenance/self-healing:** durable fixture/live provenance and live rebuild.
11. **M11 — freshness controls:** upstream freeze proved, **14** alternatives rejected as unsafe, dashboard staleness surfaced, deterministic boundary tests and live operational gate implemented.
12. **M12 — pipeline run audit:** append-only Parquet run ledger, success/failure capture, DuckDB-readable evidence, CI artifact, and documented concurrency/durability limits.
13. **M13 — concurrency-safe ledger:** per-run part files written through atomic renames, a derived snapshot that preserves the existing query and artifact contract, a deterministic replay of the lost update it removes, and a **12-process** parallel write proof in CI.
14. **M14 — published evidence that cannot sleep:** a scheduled workflow that persists the run ledger to an append-only `evidence` branch and renders a static, self-checking status page — one that flips itself to `STALE` in the reader's browser, shows missing days instead of hiding them, refuses to render on an empty ledger, and publishes failed runs as loudly as successful ones.

</details>

---

MIT — see [LICENSE](LICENSE).
