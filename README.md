# econ-lakehouse

[![pipeline](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml/badge.svg)](https://github.com/umutseve4/econ-lakehouse/actions/workflows/pipeline.yml)

Medallion-architecture data warehouse for Turkish macroeconomic data.

**Problem:** CPI/macro data lives scattered across APIs and CSV dumps. Analytical
SQL written directly against raw files is untyped, unvalidated, and
unreproducible. This repo builds a small but real lakehouse: validated bronze
Parquet, typed silver views, analytical gold marts - with data-quality gates at
every layer and a CI pipeline that rebuilds everything from scratch on each push.

## Architecture

```
CSV / API source
      |  ingest/ingest.py  - schema contract validated BEFORE any write
      v
warehouse/bronze/cpi/year=YYYY/data.parquet     (partitioned, idempotent upsert)
      |  dbt + DuckDB
      v
silver.stg_cpi           - typed, deduplicated view over the Parquet lake
      |
      v
gold.mart_inflation_yoy  - year-over-year inflation per COICOP item
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
python ingest/ingest.py --source data/sample/cpi_fixture.csv --out warehouse/bronze
DBT_PROFILES_DIR=. dbt build --project-dir .
```

## Data

`data/sample/cpi_fixture.csv` is a **synthetic fixture** shaped like TUIK CPI
sub-indices (COICOP codes CP00/CP01/CP07). It exists to exercise the pipeline
deterministically; it is **not** real official statistics. In CI the pipeline
switches to **real TCMB EVDS data** whenever the `EVDS_API_KEY` secret is set.

## Status (honest)

- **Verified locally:** bronze ingest - 12/12 unit tests + end-to-end run PASS.
- **Verified in CI:** live EVDS (TCMB) fetch -> bronze -> dbt silver/gold build +
  data-quality tests + idempotency proof (re-ingest changes no row counts).
- **Provenance:** every bronze row carries `source_name` and `fetched_at`
  (UTC, ISO-8601); silver resolves any residual duplicate by latest fetch.
- **Not yet built:** late-revision snapshot tests, Airflow/Dagster
  orchestration, Docker image. Tracked as milestones below.

## Milestones

1. **M1 - vertical slice (done, CI-green):** fixture CSV -> bronze -> silver -> gold, all gated.
2. **M2 - real data (done, CI-green):** EVDS 3 API ingest, live fetch verified in CI.
3. **M3 - incremental (done, CI-green):** provenance columns + idempotent upsert; next: snapshot tests for late revisions.
4. **M4 - orchestration:** Dockerized scheduled runs, failure alerting.

## License

MIT - see [LICENSE](LICENSE).
