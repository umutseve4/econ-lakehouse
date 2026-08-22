# econ-lakehouse

[![pipeline](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml)
[![freshness-gate](https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/freshness-gate.yml)

**Live demo:** [econ-lakehouse-umut.streamlit.app](https://econ-lakehouse-umut.streamlit.app/)

A tested medallion-architecture warehouse for Turkish macroeconomic data. It turns API/CSV input into validated bronze Parquet, typed dbt silver models, analytical gold marts, a read-only API, and a Streamlit dashboard.

> **Freshness notice (verified 2026-08-22):** the official production source `TP.FG.J0` currently ends at **2026-01**. The warehouse is live-source, but its newest CPI observation is not current. The dashboard now displays the exact observation date and lag instead of presenting the value as current. See [Data freshness policy](docs/data-freshness.md).

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
```

| Layer | Main tools | Enforced checks |
|---|---|---|
| Bronze | pandas, pyarrow, fsspec | schema, ISO dates, positive values, no duplicate `(date, item_code)`, provenance, idempotent upsert |
| Silver | dbt, DuckDB | typing, `not_null`, uniqueness, positivity, latest-fetch deduplication |
| Gold | dbt table | non-null YoY metric, non-empty mart, revision history |
| Serving | FastAPI, Streamlit | read-only DB, parameterized SQL, response limits, provenance and freshness disclosure |
| Operations | GitHub Actions, Docker, Dagster | clean rebuilds, remote-storage smoke, scheduled alerting, live freshness gate |

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

## Verified status

- Ingest: **12/12** unit tests plus end-to-end pipeline.
- Serving API: **13** fixture-based tests, including SQL injection and limit validation.
- Dashboard: **11** data/UI tests with a headless Streamlit `AppTest` render.
- Bootstrap/provenance: **8** stubbed tests plus fixture-mode end-to-end build.
- Freshness policy: exact boundary tests for **3 months = pass** and **4 months = fail**, CSV-tail detection, scheduled/manual live enforcement.
- CI: Docker smoke, Dagster materialization, MinIO remote-storage path, dbt tests, idempotency proof, and revision-history proof.
- Deployment: Streamlit Community Cloud is reachable and uses official EVDS input when the secret is configured; the newest observation may still be stale and is disclosed in-product.

## Milestones

1. **M1 — vertical slice:** fixture → bronze → silver → gold, quality-gated.
2. **M2 — real source:** EVDS 3 ingestion verified in CI.
3. **M3 — incremental:** provenance and idempotent upsert.
4. **M4 — operations:** Docker, single entrypoint, schedule, failure issue.
5. **M5 — durability:** S3-compatible bronze and SCD Type 2 revisions.
6. **M6 — serving:** read-only FastAPI with tested filters.
7. **M7 — orchestration:** Dagster assets, check, job, schedule.
8. **M8 — dashboard:** isolated query layer and headless UI test.
9. **M9 — cloud deploy:** self-bootstrapping Streamlit deployment.
10. **M10 — provenance/self-healing:** durable fixture/live provenance and live rebuild.
11. **M11 — freshness controls:** upstream freeze proved, **14** alternatives rejected as unsafe, dashboard staleness surfaced, deterministic boundary tests and live operational gate implemented.

## License

MIT — see [LICENSE](LICENSE).
