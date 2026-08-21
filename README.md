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
- **Not yet built:** late-revision snapshot tests, Airflow/Dagster-style DAG
  orchestration, remote storage (S3/minio). Tracked as milestones below.

## Milestones

1. **M1 — vertical slice (done, CI-green):** fixture CSV → bronze → silver → gold, all gated.
2. **M2 — real data (done, CI-green):** EVDS 3 API ingest, live fetch verified in CI.
3. **M3 — incremental (done, CI-green):** provenance columns + idempotent upsert; next: snapshot tests for late revisions.
4. **M4 — orchestration (done, CI-green):** Docker image + `orchestrate.py` entrypoint, weekly scheduled runs, auto-issue on scheduled failure.
5. **M5 — durability:** remote object storage for bronze (S3-compatible), late-revision snapshot tests.

## License

MIT — see [LICENSE](LICENSE).
