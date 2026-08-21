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
| Bronze | pandas + pyarrow | schema contract, positive values, no dupes, ISO dates |
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

`data/sample/cpi_fixture.csv` is a **synthetic fixture** shaped like TÜİK CPI
sub-indices (COICOP codes CP00/CP01/CP07). It exists to exercise the pipeline
deterministically; it is **not** real official statistics. Wiring the real
EVDS/TÜİK API into `ingest/` is the next milestone.

## Status (honest)

- **Verified locally:** bronze ingest — 6/6 unit tests + end-to-end run PASS.
- **Verified in CI:** dbt silver/gold build + data-quality tests (see badge; the
  first green run is the acceptance evidence for this layer).
- **Implemented + unit-tested offline:** EVDS (TCMB) API client
  (`ingest/evds_client.py`) — parsing is verified against a recorded fixture;
  the **live fetch is not yet verified** because it requires an `EVDS_API_KEY`
  secret. CI automatically switches from the synthetic fixture to real EVDS
  data once the repository secret is configured (Settings → Secrets →
  Actions → `EVDS_API_KEY`; free key from https://evds2.tcmb.gov.tr).
- **Not yet built:** incremental loads, Airflow/Dagster orchestration,
  Docker image. Tracked as milestones below.

## Milestones

1. **M1 — vertical slice (this repo now):** fixture CSV → bronze → silver → gold, all gated, CI-green.
2. **M2 — real data (client done, awaiting key):** EVDS API ingest; next: retry/rate-limit handling + provenance columns (source, fetched_at).
3. **M3 — incremental:** append-only monthly loads, snapshot tests for late revisions.
4. **M4 — orchestration:** Dockerized scheduled runs, failure alerting.

## License

MIT — see [LICENSE](LICENSE).
