# Data freshness policy

## Current production limitation

The live pipeline intentionally remains on TCMB EVDS series `TP.FG.J0` because it is the identified source used by the existing mart. As verified on 2026-08-22, the upstream series stops at **2026-01**. The dashboard value is therefore historical and must not be interpreted as current inflation.

A batch diagnostic tested **14 candidate series**. The decision set was empty: every historically YoY-compatible candidate was stale, while every current candidate was materially incompatible. In particular, `TP.TUFE1YI.T1` differed from `TP.FG.J0` by a mean **15.1540 percentage points** and a maximum **72.1737 percentage points** across **121 overlapping YoY months**. This cannot be explained by simple index rebasing because a constant base factor cancels in the YoY ratio.

## Policy

- Production freshness limit: **3 calendar months**.
- The dashboard always shows the newest observation date and exact lag.
- A lag of **0–3 months** is fresh; **4+ months** is stale.
- Scheduled and manually dispatched live checks fail when the limit is exceeded and open one deduplicated `data-freshness` issue.
- Pull requests run deterministic boundary tests only; an upstream freeze cannot make unrelated code unmergeable.
- A replacement series must have authoritative metadata and pass a full-history YoY compatibility review. Old and new methodologies must never be silently spliced.

## Operational commands

- Offline policy tests: `python tests/test_freshness.py`
- Gate a fetched CSV: `python ingest/freshness_gate.py --csv data/evds/cpi_evds.csv --max-lag-months 3`
- Diagnose request variants: `python ingest/evds_freshness.py`
- Compare candidate history: `python ingest/evds_series_compare.py`
- Sweep known candidates: `python ingest/evds_candidate_sweep.py`
