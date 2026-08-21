# econ-lakehouse

[![pipeline](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml)

Medallion-architecture data warehouse for Turkish macroeconomic data.

**Problem:** CPI/macro data lives scattered across APIs and CSV dumps. Analytical
SQL written directly against raw files is untyped, unvalidated, and
unreproducible. This repo builds a small but real lakehouse: validated bronze
Parquet, typed silver views, analytical gold marts — with data-quality gates at
every layer and a CI pipeline that rebuilds everything from scratch on each push.

## Architecture

```
CSV / API source
      │  ingest/ingest.py  — schema contract validated BEFORE any write
      ▼
warehouse/bronze/cpi/year=YYYY/data.parquet     (append-only, partitioned)
      │  dbt + DuckDB
      ▼
silver.stg_cpi           — typed, deduplicated view over the Parquet lake
      │
      ▼
gold.mart_inflation_yoy  — year-over-year inflation per COICOP item
```

| Layer  | Tool | Quality gate |
|--------|------|--------------|
| Bronze | pandas + pyarrow | schema contract, positive values, no dupes, ISO dates, provenance stamp (source_name, fetched_at), idempotent upsert on (date, item_code) |
| Silver | dbt view on DuckDB | `not_null` tests + singular uniqueness/positivity tests |
| Gold   | dbt table | `not_null` on the YoY metric, non-empty check in CI |

## Quickstart

```bash
pip install -r requirements.txt
python tests/test_ingest.py                                   # unit tests
python orchestrate.py                                         # full pipeline (fixture mode)
EVDS_API_KEY=... python orchestrate.py                        # full pipeline (live TCMB data)
```

### Docker

```bash
docker build -t econ-lakehouse .
docker run --rm econ-lakehouse                        # fixture mode
docker run --rm -e EVDS_API_KEY=... econ-lakehouse    # live mode
```

The container runs `orchestrate.py`: fetch → bronze ingest → idempotency
proof → dbt build → gold sanity check, and exits non-zero on any failure.

### Serving API

```bash
uvicorn serve.app:app --port 8000
curl http://localhost:8000/health                          # {"status":"ok","gold_rows":N}
curl 'http://localhost:8000/v1/inflation?year=2024&limit=5'
curl http://localhost:8000/v1/inflation/latest             # newest observation per item
```

Read-only FastAPI layer over the gold mart (`mart_inflation_yoy`). The
warehouse is opened `read_only=True`, filters are fully parameterized, and
`limit` is capped at 1000. Interactive docs at `/docs` (OpenAPI). Point it at
another warehouse with `LAKE_DB=/path/to.duckdb`.

### DAG orchestration (Dagster)

```bash
pip install dagster dagster-webserver
dagster dev -f orchestration/definitions.py   # asset graph UI at localhost:3000
```

The pipeline is also expressed as a Dagster **asset graph**
(`bronze_cpi → warehouse_marts`, plus a `gold_nonempty` asset check), with a
`cpi_pipeline_job` and a weekly schedule mirroring the CI cron. Assets shell
out to the same entrypoints CI verifies (`ingest/ingest.py`, `dbt build`), so
orchestration adds lineage, retries, and observability without forking the
pipeline logic. The idempotency proof runs inside the bronze asset on every
materialization. CI materializes the whole graph in-process in fixture mode
(`dagster-orchestration` job, `tests/test_dag.py`).

### Dashboard (Streamlit)

```bash
pip install streamlit
streamlit run dashboard/app.py            # UI at localhost:8501
```

Interactive dashboard over the gold mart: latest YoY inflation per item
(`st.metric`), filterable time-series chart, raw data table, CSV export.
Presentation and data access are separated — every query lives in
`dashboard/data.py` (read-only DuckDB connection, parameterized SQL) so the
data layer is unit-tested independently of the UI. CI renders the whole app
headlessly via Streamlit's `AppTest` against a fixture warehouse
(`dashboard-smoke` job, `tests/test_dashboard.py`). Point it at another
warehouse with `LAKE_DB=/path/to.duckdb`.

### Deploy to Streamlit Community Cloud

The dashboard is self-bootstrapping: on a fresh container (no
`warehouse/econ.duckdb`) it runs the full pipeline once via
`dashboard/bootstrap.py` → `orchestrate.py` — live TCMB EVDS data when
`EVDS_API_KEY` is configured, honestly-labeled synthetic fixture otherwise.

1. Go to [share.streamlit.io](https://share.streamlit.io) → **New app** →
   pick this repo, branch `main`, main file `dashboard/app.py`.
2. In **Advanced settings → Secrets** add: `EVDS_API_KEY = "your-key"`.
3. Deploy. First load takes ~1–2 min (pipeline cold start), then it's cached.

### Scheduling & alerting

CI runs the full pipeline weekly (`cron: 17 6 * * 1`). If a **scheduled** run
fails, the `alert-on-failure` job automatically opens a GitHub issue labeled
`pipeline-failure` linking to the failing run — silent breakage (e.g. an
upstream EVDS API change) surfaces without anyone watching CI.

## Data

`data/sample/cpi_fixture.csv` is a **synthetic fixture** shaped like TÜİK CPI
sub-indices (COICOP codes CP00/CP01/CP07). It exists to exercise the pipeline
deterministically; it is **not** real official statistics. In CI the pipeline
switches to **real TCMB EVDS data** whenever the `EVDS_API_KEY` secret is set.

## Status (honest)

- **Verified locally:** bronze ingest — 12/12 unit tests + end-to-end run PASS.
- **Verified in CI:** live EVDS (TCMB) fetch → bronze → dbt silver/gold build +
  data-quality tests + idempotency proof (re-ingest changes no row counts).
- **Provenance:** every bronze row carries `source_name` and `fetched_at`
  (UTC, ISO-8601); silver resolves any residual duplicate by latest fetch.
- **Dockerized:** single-entrypoint `orchestrate.py`; image built and run
  end-to-end in CI (`docker-smoke` job); scheduled-run failures auto-open a
  GitHub issue.
- **Remote storage:** bronze lake runs unchanged on S3-compatible object
  storage via an fsspec URI (`--out s3://bucket/prefix`,
  `LAKE_S3_ENDPOINT` for MinIO); verified end-to-end in CI against a real
  MinIO container (`remote-storage` job).
- **Late-revision history:** dbt snapshot (SCD Type 2, check strategy on
  `index_value`) captures TCMB revisions as closed/open versions; a CI test
  proves a revised value produces exactly one closed and one current version.
- **Serving:** read-only FastAPI endpoints over the gold mart (`/health`,
  `/v1/inflation`, `/v1/inflation/latest`); 13 fixture-based unit tests
  (incl. SQL-injection and limit-validation checks) plus a CI smoke test
  against the real pipeline-built warehouse.
- **DAG orchestration:** Dagster asset graph (`bronze_cpi → warehouse_marts`
  + `gold_nonempty` check) with job + weekly schedule; full in-process
  materialization verified in CI (`dagster-orchestration` job).
- **Dashboard:** Streamlit UI over the gold mart (metrics, filterable chart,
  CSV export); data layer isolated in `dashboard/data.py` (read-only,
  parameterized); 11 unit tests + headless `AppTest` render verified in CI
  (`dashboard-smoke` job).
- **Cloud-ready dashboard:** cold-start bootstrap (`dashboard/bootstrap.py`)
  builds the warehouse on first request via the single-entrypoint pipeline;
  5 stubbed unit tests + a real fixture-mode e2e bootstrap verified in CI.
- **Not yet deployed:** the live Streamlit Community Cloud URL (manual step).

## Milestones

1. **M1 — vertical slice (done, CI-green):** fixture CSV → bronze → silver → gold, all gated.
2. **M2 — real data (done, CI-green):** EVDS 3 API ingest, live fetch verified in CI.
3. **M3 — incremental (done, CI-green):** provenance columns + idempotent upsert.
4. **M4 — orchestration (done, CI-green):** Docker image + `orchestrate.py` entrypoint, weekly scheduled runs, auto-issue on scheduled failure.
5. **M5 — durability (done, CI-green):** S3-compatible remote storage for bronze (fsspec + MinIO in CI), dbt snapshot for late revisions with an end-to-end revision test.
6. **M6 — serving (done, CI-green):** read-only FastAPI over the gold mart, parameterized filters, fixture unit tests + real-warehouse smoke test in CI.
7. **M7 — DAG orchestration (done, CI-green):** Dagster software-defined assets over the medallion flow, asset check on gold, job + weekly schedule, in-process materialization test in CI.
8. **M8 — dashboard (done, CI-green):** Streamlit dashboard over the gold mart, isolated read-only data layer, fixture unit tests + headless AppTest render in CI.
9. **M9 — cloud deploy (code done, CI-green; live URL pending):** self-bootstrapping dashboard for Streamlit Community Cloud — cold-start warehouse build through `orchestrate.py`, secrets passthrough, honest fixture labeling, e2e bootstrap test in CI.

## License

MIT — see [LICENSE](LICENSE).
