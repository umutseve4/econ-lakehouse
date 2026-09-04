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

## Acknowledged freezes (CI only, time-boxed)

The policy above did not change and will not change. But CI asks a different question from the dashboard. The dashboard asks *is this data current?* — for `TP.FG.J0` the answer is **no**, permanently, and users are told so in red. CI asks *is this a new problem?* Failing the scheduled run every Monday for a freeze that was investigated, documented and accepted produces a red that carries no information, and a check that can only ever be red has stopped being a check.

`ingest/freshness_waiver.py` therefore adds a **CI-only** decision layer on top of the shared policy. It never relaxes the policy; it only separates *the known freeze, still inside its review window* from *everything else*.

| state | condition | exit code |
|---|---|---|
| `fresh` | lag ≤ 3 months | 0 |
| `acknowledged_stale` | lag > 3 **and** exact series match **and** exact frozen month match **and** `accepted_on <= as_of < review_by` | 0, with a `::warning::` annotation and a step-summary entry |
| `stale` | anything else | 1, with an `::error::` annotation |

### The current record

| field | value |
|---|---|
| series | `TP.FG.J0` |
| frozen at | `2026-01` |
| accepted on | `2026-09-04` |
| review by | `2026-10-05` (**exclusive**) |
| owner | `umutseve4` |
| evidence | this document |
| tracking | [issue #32](https://github.com/umutseve4/econ-lakehouse/issues/32) |

`2026-10-05` is itself a Monday, so the acknowledgement covers exactly **four** scheduled runs — 2026-09-07, 09-14, 09-21 and 09-28 — and the gate fails again **on the 2026-10-05 cron itself**. Nobody has to remember to switch it off.

### Why this cannot become a permanent bypass

- **Exact match.** Series *and* month must match exactly. If TCMB publishes even one more month, the waiver stops matching and the gate goes red the same week.
- **Hard expiry.** `review_by` is exclusive and requires no human action to take effect.
- **Fail-closed.** Wildcards, unpadded months, month 13, string dates, `review_by <= accepted_on`, empty fields, unknown fields, duplicate records and non-waiver entries all raise at **import time**. A malformed waiver never degrades into a permissive one.
- **Omission fails closed.** `--series` defaults to `None`, and a missing or empty series can never match a waiver.
- **Statically enforced isolation.** `tests/test_freshness.py` reads `quality/freshness.py` and every `dashboard/*.py` and fails if the waiver is referenced there. The dashboard cannot start agreeing with CI by accident.

### What the acknowledgement does NOT cover

It keys on the **observation month**, not on the values. If upstream *revises* the already-published 2026-01 figures without advancing the month, the waiver still matches and this gate will not notice. That is a snapshot/revision concern, not a freshness one — see `tests/test_snapshot_revision.py`. It is out of scope here deliberately, not by oversight.

It also cannot stop a waiver from being *added*. That is an authorisation question, and the only real answer is branch protection or a CODEOWNERS rule on `ingest/freshness_waiver.py`.

### Renewing or removing a record

Do not extend `review_by` because the gate went red. Re-run the investigation first (`ingest/evds_candidate_sweep.py`), update the evidence above, and only then change the record — with the diff, the sweep result and the date reviewed like any other production change. Extending a waiver without new evidence is how a gate becomes decoration.

## Operational commands

- Offline policy tests: `python tests/test_freshness.py`
- Gate a fetched CSV: `python ingest/freshness_gate.py --csv data/evds/cpi_evds.csv --max-lag-months 3 --series TP.FG.J0`
- Evaluate against a specific date: add `--as-of 2026-10-05`
- Diagnose request variants: `python ingest/evds_freshness.py`
- Compare candidate history: `python ingest/evds_series_compare.py`
- Sweep known candidates: `python ingest/evds_candidate_sweep.py`
