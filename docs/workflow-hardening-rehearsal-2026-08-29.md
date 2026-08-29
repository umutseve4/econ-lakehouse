# Combined workflow-hardening rehearsal — 2026-08-29

## Scope and safety boundary

This document records the integration-only rehearsal of PRs #33, #34, and #35. The rehearsal is carried by draft PR #36 and is not approval to merge. `main` remains unchanged.

## Immutable identities

| Item | Identity |
|---|---|
| Base `main` / checkpoint target | `ce082af197c4de07e9b5aca2586441bc83fd137f` |
| Checkpoint branch | `checkpoint/econ-lakehouse-20260829-1552` |
| PR #33 source head | `aa317f41192270e849f761f517f27ac938179fe1` |
| PR #34 source head | `11398a5cb2fec040a3bb4e9e50151a0005f452df` |
| PR #35 source head | `b35a44bdda5ca3f95d26f85860aaa4b706036d53` |
| First combined head | `985909f21cef1a4cb56729c35570229360e3a183` |
| Draft integration PR | `#36` |

## Exact source-file equality

The combined branch preserved the source workflow files byte-for-byte at the first combined head:

| Workflow file | Git blob SHA | Source |
|---|---|---|
| `.github/workflows/run-audit.yml` | `83389f0e659b6f1ceb1a55d8337ca855fa911f1a` | PR #33 |
| `.github/workflows/freshness-gate.yml` | `b2b9a0f96d6d5e9f48f87e205e02fa8b6917004b` | PR #34 |
| `.github/workflows/pipeline.yml` | `430b4b52fc998e2dc4fc8c494b7728545512b376` | PR #35 |

Integration order: PR #35 branch ancestry, PR #33 integration commit `92807b0bc64ed51444106fe729c42c8f6ee88d06`, then PR #34 integration commit `985909f21cef1a4cb56729c35570229360e3a183`.

## First combined CI observation

Runs were triggered by draft PR #36 at exact head `985909f21cef1a4cb56729c35570229360e3a183`.

| Run ID | Job / check | Job ID | Conclusion |
|---|---|---:|---|
| `33261540569` | `dashboard-smoke` | `99124228549` | success |
| `33261540569` | `docker-smoke` | `99124228592` | success |
| `33261540569` | `remote-storage` | `99124228598` | success |
| `33261540569` | `ingest-and-transform` | `99124228620` | success |
| `33261540569` | `dagster-orchestration` | `99124228628` | success |
| `33261540569` | `publish-pr-diagnostics` | `99124369843` | success |
| `33261540569` | `alert-on-failure` | `99124401784` | skipped (expected: no upstream failure) |
| `33261540639` | `policy-tests` | `99124228695` | success |
| `33261540639` | `live-gate` | `99124229374` | skipped (expected on `pull_request`) |
| `33261540639` | `alert-on-live-failure` | `99124229394` | skipped (expected without a live-gate failure) |
| `33261540570` | `run-audit` | `99124228367` | failure |

The first observation is **not a pass**: 7 jobs succeeded, 3 jobs skipped for expected event/result conditions, and `run-audit` failed. The same exact `run-audit.yml` blob had succeeded independently on PR #33 in run `33243175090`, job `99075903928`. No workflow or application-code fix is justified without the failing step/log. This evidence-only documentation commit intentionally retriggers the unchanged workflow sources; its result must be recorded separately and must not erase the initial failure.

## Known evidence limits

This rehearsal does not prove scheduled live EVDS continuity, two-run issue deduplication, long-term audit durability, or exact deployed Streamlit SHA. The project remains not production-ready until those gates have independent evidence.
