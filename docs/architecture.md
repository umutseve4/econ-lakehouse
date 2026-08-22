# System architecture

![econ-lakehouse architecture](architecture.svg)

## Data flow

1. **Source** — TCMB EVDS supplies the configured macroeconomic series.
2. **Bronze** — the ingestion layer preserves raw observations and provenance.
3. **Silver** — dbt cleans, types, validates, and standardizes the observations.
4. **Gold** — dbt produces analytics-ready facts and marts.
5. **Serving** — FastAPI exposes data while Streamlit presents the analytical dashboard.
6. **Orchestration and controls** — Dagster coordinates execution; GitHub Actions runs deterministic CI plus the scheduled or manual live freshness gate.

## Freshness contract

The shared policy in `quality/freshness.py` allows a maximum lag of **3 calendar months**. The dashboard discloses the latest observation and lag. The live gate fails when the lag exceeds the contract and its workflow is configured to create one deduplicated GitHub issue for `TP.FG.J0`.

## Evidence boundary

This diagram describes the repository architecture at merge commit `cee7161255edc93e1846af947e2adffb91355063`. It does not by itself prove the currently deployed Streamlit revision or a successful post-merge workflow execution; those require independent run and deployment evidence.
