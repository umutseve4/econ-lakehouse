# econ-lakehouse

[![pipeline](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml)
[![freshness-gate](https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml)
[![run-audit](https://github.com/umutseve4/econ-lakehouse/actions/workflows/run-audit.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/run-audit.yml)

**Deployment URL:** [econ-lakehouse-umut.streamlit.app](https://econ-lakehouse-umut.streamlit.app/)

A tested medallion-architecture warehouse for Turkish macroeconomic data. It turns API/CSV input into validated bronze Parquet, typed dbt silver models, analytical gold marts, a read-only API, and a Streamlit dashboard.

> **Freshness notice (verified 2026-08-22):** the official production source `TP.FG.J0` currently ends at **2026-01**. The warehouse is live-source, but its newest CPI observation is not current. The dashboard is designed to display the exact observation date and lag instead of presenting the value as current. See [Data freshness policy](docs/data-freshness.md).

> **Deployment evidence boundary (re-verified 2026-09-04T22:25Z):** the Streamlit Community Cloud application is currently **dormant**. The URL returns "This app has gone to sleep due to inactivity" instead of the dashboard, so the deployed commit SHA cannot be verified while it sleeps. The link is retained for portfolio access and wakes on click, but no always-on availability is claimed and deployment is tracked separately from code and CI evidence.

## Why this exists

Analytical SQL written directly against raw files is untyped, unvalidated, and difficult to reproduce. This project makes the full path explicit and testable:

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
        └── warehouse/run_log.parquet (append-only audit record)
```

| Layer | Main tools | Enforced checks |
|---|---|---|
| Bronze | pandas, pyarrow, fsspec | schema, ISO dates, positive values, no duplicate `(date, item_code)`, provenance, idempotent upsert |
| Silver | dbt, DuckDB | typing, `not_null`, uniqueness, positivity, latest-fetch deduplication |
| Gold | dbt table | non-null YoY metric, non-empty mart, revision history |
| Serving | FastAPI, Streamlit | read-only DB, parameterized SQL, response limits, provenance and freshness disclosure |
| Operations | GitHub Actions, Docker, Dagster, Parquet audit log | clean rebuilds, remote-storage smoke, scheduled alerting, live freshness gate, one run record per orchestration attempt |

## Quickstart

```bash
pip install -r requirements.txt
python tests/test_ingest.py
python tests/test_freshness.py
python orchestrate.py
```

Use official EVDS input only through an environment variable; never place the key in a URL, source file, log, or commit:

```bash
EVDS_API_KEY=... python orchestrate.py
```

### Docker

```bash
docker build -t econ-lakehouse .
docker run --rm econ-lakehouse

docker run --rm -e EVDS_API_KEY=... econ-lakehouse
```

The single entrypoint performs fetch → bronze ingest → idempotency proof → dbt build → gold sanity check and exits non-zero on failure.

### API

```bash
uvicorn serve.app:app --port 8000
curl http://localhost:8000/health
curl 'http://localhost:8000/v1/inflation?year=2024&limit=5'
curl http://localhost:8000/v1/inflation/latest
```

The API opens DuckDB with `read_only=True`, uses parameterized filters, and caps `limit` at **1000**. OpenAPI documentation is available at `/docs`. Set `LAKE_DB=/path/to.duckdb` to use another warehouse.

### Dashboard

```bash
streamlit run dashboard/app.py
```

The Streamlit app shows latest available YoY observations, an interactive time series, raw data, and CSV export. Data access is isolated in `dashboard/data.py`; freshness policy is pure/testable in `quality/freshness.py`. On cold start, `dashboard/bootstrap.py` invokes the same `orchestrate.py` pipeline used by CI and Docker. `warehouse/provenance.json` records fixture/live mode, source, UTC build time, and gold row count.

### Dagster

```bash
pip install dagster dagster-webserver
dagster dev -f orchestration/definitions.py
```

The asset graph is `bronze_cpi → warehouse_marts` plus a `gold_nonempty` asset check. CI materializes it in-process; Dagster adds lineage, retries, scheduling, and observability without creating a second pipeline implementation.

## Data freshness: explicit limitation, not a silent series swap

The production mapping remains `TP.FG.J0 → CP00`. Live diagnostics proved that extending `endDate`, removing aggregation/formula parameters, and requesting the bare series all return the same non-null tail ending at **2026-01**. The freeze is upstream, not a parser or dbt defect.

A sweep tested **14 candidate series**. No series was both current and historically compatible. `TP.TUFE1YI.T1` reaches **2026-07**, but across **121 overlapping YoY months** its mean absolute difference from `TP.FG.J0` is **15.1540 percentage points** and its maximum difference is **72.1737 percentage points at 2022-10**. A simple index rebasing cannot cause that: the constant base factor cancels in the YoY ratio.

Therefore this repository does **not** splice a different methodology onto the old history. The implemented policy is:

- **0–3 calendar months:** fresh/pass.
- **4+ calendar months:** stale/fail.
- Dashboard: exact newest date, exact month lag, and prominent stale warning.
- Every PR/push: deterministic `3`-month-pass and `4`-month-fail tests.
- Weekly/manual live run: fetch `TP.FG.J0`, fail beyond **3 months**, and open one deduplicated `data-freshness` issue.
- Future migration: require authoritative series metadata and full-history compatibility evidence, then rebuild the whole history and document the methodology break.

Operational evidence and commands are documented in [docs/data-freshness.md](docs/data-freshness.md).

## Data and storage

`data/sample/cpi_fixture.csv` is synthetic and exists only for deterministic testing. It is **not** official statistics. Live mode uses TCMB EVDS. Bronze data can also target S3-compatible storage through an fsspec URI; CI verifies the path against a real MinIO service. dbt snapshots retain SCD Type 2 revision history when upstream values change.

## CI and alerting

The main workflow rebuilds and verifies ingestion, dbt models/tests, idempotency, API, dashboard, Dagster, Docker, and S3-compatible storage. It runs weekly at `17 6 * * 1`; scheduled pipeline failures open a deduplicated `pipeline-failure` issue.

The independent freshness workflow runs deterministic policy tests on code changes and the live gate weekly at `47 6 * * 1` or on manual dispatch. Keeping the live upstream check separate prevents a known external freeze from making unrelated pull requests unmergeable while still producing an operational failure signal.

The independent run-audit workflow executes the fixture pipeline twice, checks for exactly **2 rows** and **2 unique `run_id` values**, exercises the failure path, reads the Parquet log with DuckDB, and uploads the audit artifact.

## Run observability

Every `orchestrate.py` attempt writes one append-only record to `warehouse/run_log.parquet` without changing the pipeline's original exit semantics. The record includes run identity and timing, success/failure state, mode and source, bronze/gold row counts, step totals, failed step, and Git SHA. Query examples, the schema contract, CI evidence, and concurrency limitations are documented in [docs/observability.md](docs/observability.md).

This audit layer is intentionally local and single-writer: the current read-modify-write append is not atomic, concurrent runs can lose rows, and the audit history is not yet persisted to S3/MinIO. These limitations prevent a production-ready claim.

## Evidence status

- Ingest: **tested** — **12/12** unit tests plus end-to-end pipeline.
- Serving API: **tested** — **13** fixture-based tests, including SQL injection and limit validation.
- Dashboard: **tested** — **11** data/UI tests with a headless Streamlit `AppTest` render.
- Bootstrap/provenance: **tested** — **8** stubbed tests plus fixture-mode end-to-end build.
- Freshness policy: **tested** — exact boundary tests for **3 months = pass** and **4 months = fail**, CSV-tail detection, and scheduled/manual live enforcement code.
- Run audit: **implemented and PR-tested** — append-only Parquet history, success/failure paths, independent DuckDB read, and artifact contract. Operational concurrent-write durability is not implemented.
- PR #14: **merged** — squash merge SHA `b4bbc875fc32ba075fa00fff20b5a4a0659f0900`; that SHA was verified as `main` HEAD during closure.
- Post-merge `main` CI: **verified 2026-09-04T22:25Z** at `main` HEAD `035fddcc5e027241c2c02fb54012266b8da11c25` (`docs: add contribution guidance (#42)`, committed 2026-09-04T07:10:27Z). All three workflows succeeded on that exact SHA: `pipeline` run **#114** (`ingest-and-transform`, `dashboard-smoke`, `docker-smoke`, `remote-storage`, `dagster-orchestration` all SUCCESS; `alert-on-failure` SKIPPED by design), `run-audit` run **#64** SUCCESS, and `freshness-gate` run **#82** (`policy-tests` SUCCESS; `live-gate` and `alert-on-live-failure` SKIPPED on `push`). This supersedes the earlier closure gap at `b4bbc875fc32ba075fa00fff20b5a4a0659f0900`; PR-head checks are still not treated as merge-commit checks.
- Freshness issue deduplication: **implemented, operationally unverified** — a two-run manual proof is still required.
- Deployment: **verified dormant 2026-09-04T22:25Z** — `econ-lakehouse-umut.streamlit.app` serves the Streamlit Community Cloud inactivity sleep page, so the dashboard is not reachable without a manual wake and the deployed SHA is unverifiable. Always-on availability is **not claimed**; a published evidence page that cannot sleep is tracked as the next milestone (M13).
- Production-ready: **not claimed**.

## Milestones

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

## License

MIT — see [LICENSE](LICENSE).
