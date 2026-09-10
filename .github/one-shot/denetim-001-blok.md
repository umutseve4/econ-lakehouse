---

## Audit 001: is the Turkish CPI gap an arithmetic error?

For August 2026 the official institute (TUIK) published **31.51%** annual CPI
inflation. The independent group (ENAG) published **49.03%** for the same month.
A common claim on both sides is that the other one cannot even add up correctly.

This repository now contains an audit that tests exactly that claim, applying one
identical test to both institutions.

| | internal arithmetic test | reproducibility scorecard |
|---|---|---|
| **TUIK** | PASS, 64 of 64 months clean | 8/8 |
| **ENAG** | PASS, uses 17.9% of the rounding envelope | 2/8 |

**Neither side has an arithmetic error.** The 17.5 point gap does not come from
addition. It comes from the basket, the weights and the price collection method.
The real asymmetry is not accuracy but auditability: a third party can rebuild the
TUIK figure end to end and cannot rebuild the ENAG one.

```bash
python audits/001-tufe-aritmetigi/audit.py --check
```

No dependencies, standard library only. Every number in the report is recomputed
from the raw CSV; if one drifts, the exit code is 1 and CI turns red.

- **[Read the audit](audits/001-tufe-aritmetigi/README.md)** (in Turkish)
- [Pre-registered protocol](audits/001-tufe-aritmetigi/PROTOCOL.md), committed in
  its own earlier commit; the ordering is asserted from git history by a test
- [Appendix A](audits/001-tufe-aritmetigi/EK-A-artik-tablosu.md), the full 64 row
  residual table, regenerated and byte-compared by CI on every run
- [Sources](audits/001-tufe-aritmetigi/data/SOURCES.md), one code per data cell

The report also carries its own error log. The first published version named the
wrong month for the largest residual. That version **failed CI** at commit
`f55ca86`, the correction passed at `55a2beb`, and both states remain in history.
The guard was proved by a real break, not by a claim.

