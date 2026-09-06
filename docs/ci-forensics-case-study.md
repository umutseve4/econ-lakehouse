> **Related:** [`docs/observability.md`](observability.md) · [`docs/runbooks/actions-inactivity.md`](runbooks/actions-inactivity.md) · live evidence page: <https://umutseve4.github.io/econ-lakehouse/>

# Three red builds, three different verdicts

On **2026-09-05** the CI for this repository went red four separate times. The
temptation in that situation is to re-run until green and move on. Two of these
failures would have gone green on a re-run — and one of them was a genuine
data-loss defect that had been silently under-reporting runs for weeks.

So the useful skill is not *fixing* a red build. It is **deciding what kind of
red it is before touching anything**, and being able to prove the decision
afterwards.

This document is the record of how that was done here. It is deliberately
written to include the things that were *not* established, because a diagnosis
that only reports its successes is not a diagnosis.

---

## The one-line summary

| # | Symptom | Verdict | How it was decided | Outcome |
|---|---|---|---|---|
| 1 | `docker-smoke` failing at a different step on each run | **External, transient** | One commit, three runs, three different results | Mitigated with bounded retry (#62), never masked |
| 2 | `dashboard-smoke` step 7 failing in 5 s against a 7/8/8 s baseline | **Flake** | Same commit re-dispatched → passed in 8 s | Tracked as its own issue (#63), no code changed |
| 3 | `run-audit` step 7 failing in exactly 4 s, pass or fail | **Real defect** | The duration did not change → the step ran to completion and reported a true negative | Root-caused, fixed, mutation-verified (#64) |
| 4 | `run-audit` step 7 exiting **134** | **Unexplained** | Non-deterministic: 1 abort / 1 clean on the identical tree | Merged with a stated monitoring debt, not called "fixed" |

---

## Incident 1 — when the failure moves, the cause is outside the diff

`main` turned red after two merges. `#58` was a **comment block**. `#59` added a
gated step that **no automatic trigger can reach**. Neither has a causal path to
a test failure, yet the runs were red.

The failing step moved between runs:

| Run | Trigger | Commit | Failing step |
|---|---|---|---|
| 10:38Z | push | `28dffa88` | `audit` step 9 · `dashboard-smoke` step 7 |
| 10:45Z | push | `3542cee5` | `audit` step 7 · `docker-smoke` step 5 |
| 10:42Z | branch push | same tree | **all green** |

Then the decisive experiment — **one commit, three runs**, `pipeline` on
`3542cee5`:

| Run | Event | `docker-smoke` result |
|---|---|---|
| push run | push | step 5 failed, step 3 passed in 44 s |
| #142 | `workflow_dispatch` | step 3 `Build image` failed in **5 s** |
| #143 | `workflow_dispatch` | **all six jobs SUCCESS**, step 3 49 s, step 5 10 s |

The 5-second death is the tell. On host runners the same dependency stack
installs in 37–43 s, and in that same run the quay.io MinIO pull succeeded in
4 s. A build that dies in 5 s never reached `pip install` — it died pulling the
`docker.io` base image.

**Three results from one immutable tree means the variable is not in the tree.**

The reading of each branch was written into the issue **before** the third run
finished, so the conclusion could not be retrofitted to whatever arrived.

Mitigation (PR **#62**, merged `a78bc927`): three attempts with 10 s / 20 s
backoff, printing `build_attempts_used` so a retried success stays visible, and
**still `exit 1` after three consecutive failures**.

> A retry that swallows the real error is worse than no retry.

The commit message says what the change *is*: "**mitigation, not diagnosis**."
The `docker.io` error string was never read, so the root cause was never named,
and the merge did not pretend otherwise.

---

## Incident 2 — the flake that appeared inside the hardening PR

PR #62's own CI came back red — but in a **different job**. `docker-smoke`
(the job it hardened) passed; `dashboard-smoke` step 7 `Cold-start bootstrap
e2e` failed.

The PR's diff touches two `run:` bodies inside `docker-smoke`, and that was
proven structurally with a PyYAML job-by-job comparison *before* the push. No
causal path.

The numbers:

| | Duration |
|---|---|
| Baseline on parent commit `3542cee5` (3 runs) | 7 s, 8 s, 8 s — all pass |
| Failing run | **5 s** |
| Re-dispatch on the identical head `f4d12ac7` | **8 s — SUCCESS** |

Same commit, different outcome → flake. The re-dispatch landed exactly in the
middle of the baseline. Again the two-branch reading was posted to the PR
*before* the deciding run completed.

It was filed as **issue #63**, deliberately **not** appended to #60:

> Different job, different step, different candidate mechanisms. Compressing
> three distinct faults into one narrative is how a diagnosis gets lost.

A secondary finding surfaced while writing it up: `dashboard/bootstrap.py`
invokes `orchestrate.py` **without** `--mode`, i.e. it decides from the
environment. Harmless today, because `dashboard-smoke` defines no
`EVDS_API_KEY` — but the day one is added, the step fails silently with the
wrong message. Recorded rather than "fixed while I was in there".

---

## Incident 3 — the red that was telling the truth

`run-audit` step 7 kept failing. It had every surface feature of the two flakes
above: intermittent, in CI only, 15/15 green locally.

**One number separated it.** The step took **4 seconds whether it passed or
failed** — #72 push pass, #74 push fail, #75 dispatch pass, #76 push fail.

> The `docker-smoke` and `dashboard-smoke` failures both *shortened* when they
> failed, because something external aborted them. A step whose duration does
> not change is not being aborted. It runs to completion and reports an
> assertion that came back false.

That inverted the prior. And it contradicted a hypothesis already committed to
in writing — the "both failures are on push" correlation had to be dropped,
because #72 was a push and passed.

Then the log line:

```
[PASS] no run lost under real parallelism — 12/12 rows
[FAIL] derived snapshot is complete after concurrent writes — snapshot has 11/12
```

**The parts directory was complete. The snapshot derived from it was not.**

### The defect

```python
def compact(path):
    p = Path(path)
    return _atomic_write_parquet(read_runs(p), p)   # list the parts, then replace
```

A read-modify-write. With twelve writers:

1. writer A calls `read_runs()` and lists 11 parts
2. A is descheduled
3. writer B writes part 12 and rebuilds a complete 12-row snapshot
4. A's `os.replace` lands and reinstates its stale 11-row frame

Last-writer-wins — **the exact bug class M13 had already eliminated for the
ledger, still alive in the artifact derived from it.** The module docstring says
"Losing it loses nothing: the parts are the ledger", and for `read_runs()` that
is true. But the documented DuckDB one-liner, the CI artifact contract and the
public evidence page all read the **snapshot**. A stale snapshot silently
under-reports runs — precisely the failure this ledger exists to prevent. It
self-heals on the next successful append, which is why single-writer production
never surfaced it.

### The fix, and the proof that it is a fix

`compact()` now holds an exclusive `flock` across the list-and-replace.
`write_part()` is untouched — a part write never needed coordination.

Reproduced locally first (parts 3/3, snapshot 2/3), then **mutation-verified in
both directions**:

| code | forced-interleaving proof | the original CI assertion |
|---|---|---|
| lock reverted | **FAIL** — `snapshot contains ['run-0001', 'run-0002']` | **FAIL** — CI failure reproduced locally |
| lock in place | PASS | PASS — 12/12, three consecutive runs |

A test suite that also passes against the broken code is decoration.

### A design lesson that came out of writing the test

The check that caught this fired **twice in four CI runs, and never in five
consecutive local runs**.

> A regression detector that fires half the time is not a regression detector.

So the new proof does not wait for the race — it **forces** it. Writer A takes
the lock, lists the parts and stalls; B completes an entire append and blocks;
A's bounded wait expires. **The timeout expiring is the proof that the two
rebuilds were serialised.**

### Result

PR **#64**, merged `a7c93326`. On the head `6a5586b0`: `run-audit` **#83**
`audit` **SUCCESS, 15/15 steps**. Steps 8–14 — including
`Verify audit ledger with DuckDB` — **had never executed before**, because the
abort at step 7 skipped them. `pipeline` #156, `freshness-gate` #121 and
`evidence` #11 all SUCCESS at the same head.

No assertion, threshold or timeout was weakened. The check that was failing is
still there, still asserting the same thing.

---

## Incident 4 — the one that stayed unexplained

Before that green run, the same step produced:

```
Process completed with exit code 134
```

`134 = 128 + 6` → **SIGABRT**. Not the `exit 1` a Python `AssertionError`
produces.

What was claimed, and what was not:

- **Established:** the process terminated on an abort signal.
- **Not established:** the root cause. A failing assertion *can* reach
  `abort()` through a lower layer, so "134 means the tests never asserted"
  would have been an over-claim.
- **Also retracted:** the earlier "12-process wall-clock barrier is flaky"
  inference. It came from reading the test's shape, not from a log. Labelled
  unproven and withdrawn.

Re-running on the identical tree passed 15/15. That established one thing —
**the abort is not deterministic in this diff** — and explicitly not another:

> The score on this branch is 1 abort / 1 clean. Eliminating a non-deterministic
> fault with a single green run would be exactly the mistake this PR criticises
> in its own body.

Applying the standard selectively would have been the inconsistency. So the PR
was merged on the strength of the defect it closes — with a **stated monitoring
debt**: if `run-audit` step 7 exits 134 again on `main`, it is no longer "a
flake", it is a separate bug, and the remedy will be finding the C-layer cause,
**not loosening the test**.

---

## The method, extracted

Six discriminators, each of which decided one of the calls above:

1. **Duration invariance.** A step aborted by the environment gets *shorter*
   when it fails. A step that takes the same time either way ran to completion
   and is reporting a real result.
2. **One commit, N runs.** Differing outcomes on an immutable tree put the
   variable outside the diff. Identical outcomes put it inside.
3. **Commit the reading before the result lands.** Write down what each branch
   of the experiment will mean *first*, so the conclusion cannot be
   reverse-engineered from the outcome.
4. **Local replay on the newest dependency stack** when the CI log is
   unreachable. It is a legitimate discriminator: replaying the concurrency
   suite locally on pandas 3.0.5 / pyarrow 25.0.1 / CPython 3.12.14 eliminated
   the "a new release broke it" hypothesis before any code was touched.
5. **Mutation verification, both ways.** Revert the fix and the test must go
   red. Otherwise the test proves nothing.
6. **Faithful-patch proof.** When the original file is not in hand, reconstruct
   it, revert every intentional change programmatically, and match the git blob
   SHA against the remote. That is how you know an edit is a patch and not a
   silent rewrite.

And two rules that cost something to learn:

- **Read the exit code before the diff.** `exit 2` from `pytest` is a collection
  error, not a test failure — bare `pytest tests/x.py` puts only `tests/` on
  `sys.path`, so repo-root imports fail and the job goes red **without a single
  test running**. Ask "did the tests start?" before "which test broke?".
- **Never label an issue that *describes* an alert with that alert's own dedup
  label.** The dedup query searches open issues by exactly that label and
  marker, so a genuine failure would have been appended as a comment to the
  meta-issue about the alerting.

---

## What this is not

- It is not a claim that CI here is now reliable. Issue **#60** is still open;
  the `docker.io` error string was never read and the root cause was never
  named.
- Issue **#63** is open; its raw log was never obtained.
- The SIGABRT of incident 4 is unexplained, and is recorded as a debt rather
  than a resolution.
- The evidence page this ledger feeds publishes `DATA MODE: SYNTHETIC FIXTURE`
  on every render, because the pipeline runs on a fixture. It says so on the
  page, in the banner, unconditionally.

Every number, run id, step index, duration, commit SHA and quoted log line in
this document comes from this repository's own Actions history and pull-request
record, and can be checked there.
