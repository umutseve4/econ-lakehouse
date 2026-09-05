# Runbook — scheduled workflows stop running

**Symptom:** no new runs appear under Actions for a workflow that has a `schedule:`
trigger, even though nothing was changed and nothing is failing.

This is the failure mode that silently ends a portfolio pipeline. Nothing goes red.
The last run stays green forever, and the evidence page keeps serving a cheerful
result from a pipeline that has not executed in weeks. The whole point of this
repository is to make that state visible, so it gets its own runbook.

---

## 1. What is actually scheduled here

| Workflow | Trigger | Cron (UTC) | Effect if it silently stops |
| --- | --- | --- | --- |
| `evidence.yml` | `schedule` | `23 5 * * *` — daily 05:23 | The ledger stops gaining rows; the published page ages out |
| `pipeline.yml` | `schedule` | `17 6 * * 1` — Mondays 06:17 | The weekly end-to-end rehearsal stops; `alert-on-failure` can never fire |
| `freshness-gate.yml` | `schedule` | `47 6 * * 1` — Mondays 06:47 | Upstream data going stale stops being detected |
| `run-audit.yml` | `push` (main), `pull_request`, `workflow_dispatch` | **no cron** | Not time-based — cannot be suspended for inactivity |

Both weekly crons are deliberately off the hour. GitHub's shared scheduled-run
queue is most congested at `:00`, and a `schedule` event that arrives late is
normal, not a fault. Do not treat a run that starts 10–20 minutes late as an
incident.

`run-audit.yml` has no cron, so nothing in this runbook can suspend it. Since M15
(#53, closing issue #50) it runs on every push to `main`, which is what makes its
README badge describe `main` rather than whichever pull request last happened to
touch `observability/**`.

That distinction is worth keeping straight, because it is the same
confusion in a different costume. An event-triggered workflow answers *"is the
code correct at this commit?"* A scheduled workflow answers *"does the system
still work today?"* A green `run-audit` badge on a repository whose crons were
suspended six weeks ago is **truthful and useless at the same time**: the code is
fine, and nothing has run.

---

## 2. Why they stop

**In a public repository, GitHub automatically disables scheduled workflows after
60 days of repository inactivity.** This repository is public, so the rule applies.

Two things about this rule are genuinely not documented by GitHub, and this
runbook will not pretend otherwise:

- **"Repository activity" is never defined.** GitHub's documentation uses that
  phrase without saying which events count — commit, push to the default branch,
  issue, comment, release, or something else. Do not write automation that depends
  on a specific interpretation.
- **Whether a `GITHUB_TOKEN` / `github-actions[bot]` commit resets the timer is
  not documented either.** It is widely assumed to, and an ecosystem of
  "keepalive" actions is built on that assumption, but GitHub has never confirmed
  it.

### The trap specific to this repository

`evidence.yml` commits to the `evidence` branch every single day, as
`github-actions[bot]`. It is tempting to conclude that this repository can never
go inactive and the rule cannot apply to it.

**Do not rely on that**, for two independent reasons:

1. It rests on the undocumented assumption above.
2. More importantly, it is **circular**. The daily commit is produced *by* the
   scheduled workflow. If that workflow stops for any other reason — a broken
   dependency, an expired action version, a quota change, a manual disable — the
   keepalive stops with it, at exactly the moment it is needed. A safeguard whose
   only power source is the thing it is supposed to protect is not a safeguard.

A related and better-documented rule explains a symptom you may notice while
debugging: **pushes made with `GITHUB_TOKEN` do not trigger new workflow runs.**
This is deliberate loop prevention, and it is why the daily `evidence` branch
commit never starts a `push`-triggered run. It is expected behaviour, not the bug
you are looking for.

---

## 3. How you would find out

Ranked by how much you should trust them.

**1. The evidence page turns STALE on its own — the only detector that does not
depend on Actions running.** `evidence.yml` renders with
`--stale-after-hours 30` against a daily schedule, so a single missed day is
tolerated and two are not. The check runs **in the reader's browser** against the
page's own embedded timestamp, which is what makes it survive the pipeline being
dead. A static page cannot notice its own staleness server-side; this one does it
client-side instead.

> **Currently not operational.** GitHub Pages is disabled for this repository, so
> the page is rendered and verified on every run but never published. Until an
> administrator enables it (**Settings → Pages → Build and deployment → Source:
> GitHub Actions**), this detector exists in code and is unreachable in practice.
> The `pages-preflight` job reports this in the run summary and skips `publish`
> rather than failing every run for a cause no code change can fix.

**2. GitHub's warning email — real, but not a guarantee.** GitHub does send a
"workflow will be disabled soon" notice, and community reports put it at roughly
23 days of inactivity. Two caveats: GitHub publishes no SLA for it, and it goes to
**the account that last modified the workflow**, which is not necessarily the
repository owner. Treat it as a helpful accident, not as monitoring.

**3. Looking at the Actions tab.** Reliable, but only when someone looks. That is
precisely the assumption this milestone was built to remove.

**Verify a suspicion directly:**

```bash
gh api "repos/umutseve4/econ-lakehouse/actions/workflows" \
  --jq '.workflows[] | [.state, .path] | @tsv'
```

`state` is `active` when healthy. Inactivity suspension shows as
`disabled_inactivity`; a human switching it off shows as `disabled_manually`. The
distinction matters — **re-enabling a workflow somebody disabled on purpose is
undoing a decision, not fixing a fault.** Find out which one you are looking at
before acting.

---

## 4. Recovery

**UI:** Actions → select the workflow in the left sidebar → **Enable workflow**.

**CLI:**

```bash
gh workflow enable evidence.yml   --repo umutseve4/econ-lakehouse
gh workflow enable pipeline.yml   --repo umutseve4/econ-lakehouse
gh workflow enable freshness-gate.yml --repo umutseve4/econ-lakehouse
```

**REST:**

```
PUT /repos/umutseve4/econ-lakehouse/actions/workflows/{workflow_id}/enable
```

`{workflow_id}` accepts the file name. Success is **204 No Content** — an empty
response body here means it worked. Requires `Actions: write` on a fine-grained
token, or `repo` scope on a classic token.

### Enabling is not the same as recovering

Re-enabling restores future scheduled runs. It does **not** backfill the ones that
were missed, and it does not prove the schedule is working again.

1. Trigger one run immediately so the evidence gap has a known end:
   `gh workflow run evidence.yml --repo umutseve4/econ-lakehouse`
2. Confirm that run appended a row to the `evidence` branch under
   `run_log_parts/`. The workflow is append-only by design and refuses to modify
   or delete existing parts, so the missed days stay missing. **That gap is
   accurate history — do not fabricate rows to make the page look continuous.**
3. Wait for the **next natural cron run** and confirm it fired unprompted. A
   `workflow_dispatch` run proves the workflow executes; only a `schedule` run
   proves the schedule was restored. Do not close the incident on the manual run.

---

## 5. What not to do

- **Do not add a keepalive that commits to `main` purely to reset a timer.** It
  writes fake activity into the history of a repository whose entire argument is
  that its history is trustworthy. If a keepalive is ever genuinely needed, it
  belongs on the `evidence` branch with a commit message that says exactly what it
  is and why.
- **Do not raise `--stale-after-hours` to stop the page going STALE.** The page is
  reporting correctly. Widening the threshold does not make the pipeline run; it
  only makes the page agree with the outage.
- **Do not re-enable `disabled_manually` without finding out who disabled it.**
