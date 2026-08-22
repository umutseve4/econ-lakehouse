"""Decide whether TP.TUFE1YI.T1 can replace TP.FG.J0 as the CPI source.

The freshness probe (ingest/evds_freshness.py) established that TP.FG.J0 is
frozen at 2026-01 upstream while TP.TUFE1YI.T1 continues to 2026-07. That is
necessary but not sufficient to swap: the index levels differ, so the series
may track different baskets or different bases.

Year-over-year inflation is invariant to the index base (the base cancels in
the ratio), so if both series describe the same underlying price level their
YoY paths must coincide over the overlap. This script computes exactly that
and prints the maximum absolute YoY difference.

Diagnostic only: never raises, always exits 0, never gates CI. The API key is
read from the environment and never printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
START = "01-01-2015"
CANDIDATES = ["TP.FG.J0", "TP.TUFE1YI.T1"]
# YoY paths agreeing to within this many percentage points is treated as
# "same underlying series, different base".
TOLERANCE_PP = 0.15


def _end() -> str:
    today = date.today()
    return f"31-12-{today.year}"


def _url(series: str) -> str:
    query = urllib.parse.urlencode(
        {
            "series": series,
            "startDate": START,
            "endDate": _end(),
            "type": "json",
            "frequency": "5",  # monthly
            "aggregationTypes": "avg",
            "formulas": "0",
        }
    )
    return f"{BASE_URL}?{query}"


def fetch(series: str, key: str) -> dict[str, float]:
    """Return {'YYYY-MM': value} for a series. Never raises."""
    req = urllib.request.Request(_url(series), headers={"key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[{series}] request failed: {type(exc).__name__}")
        return {}

    out: dict[str, float] = {}
    for item in payload.get("items", []):
        raw_date = item.get("Tarih")
        if not raw_date:
            continue
        value = None
        for field, raw in item.items():
            if field in {"Tarih", "UNIXTIME"}:
                continue
            if raw is None or raw == "":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            break
        if value is None:
            continue
        year, _, month = raw_date.partition("-")
        try:
            out[f"{int(year):04d}-{int(month):02d}"] = value
        except ValueError:
            continue
    return out


def yoy(levels: dict[str, float]) -> dict[str, float]:
    """Year-over-year percent change, keyed by month."""
    out: dict[str, float] = {}
    for month, value in levels.items():
        year, _, mm = month.partition("-")
        prev = f"{int(year) - 1:04d}-{mm}"
        base = levels.get(prev)
        if base:
            out[month] = (value / base - 1.0) * 100.0
    return out


def main() -> int:
    key = os.environ.get("EVDS_API_KEY", "").strip()
    print("===== EVDS SERIES COMPARISON =====")
    if not key:
        print("EVDS_API_KEY not set — skipping live comparison.")
        print("===== OTOMATIK KONTROL =====")
        print("RESULT: SKIP")
        return 0

    levels = {s: fetch(s, key) for s in CANDIDATES}
    yoys = {s: yoy(v) for s, v in levels.items()}

    for series in CANDIDATES:
        months = sorted(levels[series])
        span = f"{months[0]}..{months[-1]}" if months else "(empty)"
        print(f"[{series}] obs={len(months)} span={span}")

    a, b = CANDIDATES
    overlap = sorted(set(yoys[a]) & set(yoys[b]))
    print(f"overlapping_yoy_months={len(overlap)}")

    if not overlap:
        print("===== OTOMATIK KONTROL =====")
        print("RESULT: FAIL (no overlap — cannot justify a swap)")
        return 0

    diffs = [(m, yoys[a][m], yoys[b][m], abs(yoys[a][m] - yoys[b][m])) for m in overlap]
    print("last 12 overlapping months (month, J0_yoy%, T1_yoy%, |diff|pp):")
    for month, va, vb, d in diffs[-12:]:
        print(f"  {month}  {va:8.2f}  {vb:8.2f}  {d:6.3f}")

    worst_month, _, _, worst = max(diffs, key=lambda row: row[3])
    mean = sum(row[3] for row in diffs) / len(diffs)
    print(f"max_abs_yoy_diff_pp={worst:.4f} at {worst_month}")
    print(f"mean_abs_yoy_diff_pp={mean:.4f}")

    print("===== OTOMATIK KONTROL =====")
    verdict = "PASS (same underlying series — swap is safe)" if worst <= TOLERANCE_PP \
        else f"FAIL (diverges beyond {TOLERANCE_PP}pp — different basket, do NOT swap blindly)"
    print(f"RESULT: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
