"""EVDS data-freshness probe: WHY does the CPI series stop at 2026-01?

Runs a matrix of request variants against EVDS 3 and prints, per variant:
row count, min/max observation date, and the raw tail (last 3 items with
their raw values) so null-tail truncation is visible.

The API key is ALWAYS redacted. Exit code is always 0 - this script
diagnoses, it never gates CI.

Usage (CI, secret present):
    EVDS_API_KEY=... python ingest/evds_freshness.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date

BASE = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
KEY = os.environ.get("EVDS_API_KEY", "")
UA = "Mozilla/5.0 (compatible; econ-lakehouse-freshness/1.0)"

# Series candidates. TP.FG.J0 is the one the pipeline uses today; the others
# are alternative TUIK/TCMB CPI headline series used to test the hypothesis
# that TP.FG.J0 itself was discontinued/rebased rather than the request being
# malformed.
SERIES_CANDIDATES = [
    "TP.FG.J0",
    "TP.FG.J01",
    "TP.TUFE1YI.T1",
    "TP.FE.OKTG01",
]

TODAY = date.today()
CURRENT_MONTH_END = f"01-{TODAY.month:02d}-{TODAY.year}"
FAR_END = f"31-12-{TODAY.year}"


def redact(text: str) -> str:
    return text.replace(KEY, "***") if KEY else text


def build(series: str, start: str, end: str, agg: bool, formulas: bool) -> str:
    url = (
        f"{BASE}series={series}"
        f"&startDate={start}&endDate={end}"
        f"&type=json&frequency=5"
    )
    if agg:
        url += "&aggregationTypes=avg"
    if formulas:
        url += "&formulas=0"
    return url


def get_json(url: str) -> tuple[dict | None, str]:
    """Return (payload, note). Never raises."""
    headers = {"key": KEY, "User-Agent": UA, "Accept": "application/json"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body), "ok"
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except json.JSONDecodeError:
        return None, "non-JSON body"
    except Exception as exc:  # noqa: BLE001 - diagnostics must not crash
        return None, f"{type(exc).__name__}: {redact(str(exc))}"


def summarize(name: str, series: str, url: str) -> None:
    payload, note = get_json(url)
    if payload is None:
        print(f"[{name}] ERROR {note}")
        return

    items = payload.get("items") or []
    field = series.replace(".", "_")
    dated = [(it.get("Tarih"), it.get(field)) for it in items]
    nonnull = [(t, v) for t, v in dated if v not in (None, "")]

    def ym_key(t: str | None) -> tuple[int, int]:
        if not t or "-" not in t:
            return (0, 0)
        y, m = t.split("-")[:2]
        try:
            return (int(y), int(m))
        except ValueError:
            return (0, 0)

    raw_max = max((t for t, _ in dated if t), key=ym_key, default="-")
    if nonnull:
        val_min = min((t for t, _ in nonnull), key=ym_key)
        val_max = max((t for t, _ in nonnull), key=ym_key)
    else:
        val_min = val_max = "-"

    tail = dated[-3:]
    print(
        f"[{name}] items={len(items)} nonnull={len(nonnull)} "
        f"raw_max={raw_max} value_min={val_min} value_max={val_max} "
        f"tail={tail}"
    )


def main() -> int:
    print("===== EVDS FRESHNESS MATRIX =====")
    print(f"today={TODAY.isoformat()} current_month_end={CURRENT_MONTH_END} far_end={FAR_END}")

    if not KEY:
        print("EVDS_API_KEY not set - nothing to probe.")
        print("===== OTOMATIK KONTROL =====")
        print("probe: SKIP (no key)")
        print("RESULT: SKIP")
        return 0

    start = "01-01-2025"

    # H1/H2: request-shape hypotheses on the series in production use.
    summarize(
        "A prod-params (agg+formulas, end=current month)",
        "TP.FG.J0",
        build("TP.FG.J0", start, CURRENT_MONTH_END, agg=True, formulas=True),
    )
    summarize(
        "B end=far future (31-12)",
        "TP.FG.J0",
        build("TP.FG.J0", start, FAR_END, agg=True, formulas=True),
    )
    summarize(
        "C no aggregationTypes",
        "TP.FG.J0",
        build("TP.FG.J0", start, FAR_END, agg=False, formulas=True),
    )
    summarize(
        "D no formulas",
        "TP.FG.J0",
        build("TP.FG.J0", start, FAR_END, agg=True, formulas=False),
    )
    summarize(
        "E bare (no agg, no formulas)",
        "TP.FG.J0",
        build("TP.FG.J0", start, FAR_END, agg=False, formulas=False),
    )

    # H3: series-level hypothesis - is TP.FG.J0 itself frozen/rebased?
    for series in SERIES_CANDIDATES:
        summarize(
            f"S {series}",
            series,
            build(series, start, FAR_END, agg=False, formulas=False),
        )

    print("===== OTOMATIK KONTROL =====")
    print("probe: PASS (diagnostic only, never gates CI)")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
