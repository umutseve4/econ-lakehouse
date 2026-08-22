"""Find a CPI series that is BOTH live and YoY-compatible with TP.FG.J0.

Context: TP.FG.J0 is frozen upstream at 2026-01. TP.TUFE1YI.T1 runs to
2026-07 but its year-over-year path diverges from TP.FG.J0 by up to 72
percentage points, so it is a different basket, not a rebased twin.

This script does two things in one CI run:

1. Probes EVDS catalog/metadata endpoints so we can read what a series
   actually measures instead of inferring it from its identifier. Only HTTP
   status codes and a short body head are printed.
2. Sweeps candidate series identifiers, reporting for each: observation
   span, newest month, and the mean/max absolute YoY difference against
   TP.FG.J0 over their overlap.

Decision rule: a candidate is a drop-in replacement only if it is live
(newest >= 2026-05) AND max |YoY difference| <= 0.15pp. Anything else is a
methodology change that must be documented, not a silent swap.

Diagnostic only: never raises, always exits 0, never gates CI. The API key
is read from the environment and never printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

# EVDS 3 appends query parameters straight onto the base path (no '?').
BASE_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
START = "01-01-2015"
BASELINE = "TP.FG.J0"
TOLERANCE_PP = 0.15
LIVE_THRESHOLD = "2026-05"

CANDIDATES = [
    "TP.FG.J0",
    "TP.FG.J01",
    "TP.FG.J02",
    "TP.FG.J03",
    "TP.FG.J04",
    "TP.FG.J07",
    "TP.FE.OKTG01",
    "TP.FE.OKTG02",
    "TP.TUFE1YI.T1",
    "TP.TUFE1YI.T2",
    "TP.TUFE1YI.T3",
    "TP.TUFE1YI.TG1",
    "TP.TUFE1YI.G1",
    "TP.FG.TG01",
]

# Endpoint shapes worth testing for series metadata. We only report status
# codes and a short head of the body; nothing is parsed or trusted yet.
CATALOG_PATHS = [
    "serieList/type=json&code=TP.FG",
    "serieList/type=json&code=TP.TUFE1YI",
    "categories/type=json",
    "datagroups/type=json&mode=0&code=TP.FG",
    "series/type=json&code=TP.FG.J0",
]


def _end() -> str:
    return f"31-12-{date.today().year}"


def _url(series: str) -> str:
    query = urllib.parse.urlencode(
        {
            "series": series,
            "startDate": START,
            "endDate": _end(),
            "type": "json",
            "frequency": "5",
            "aggregationTypes": "avg",
            "formulas": "0",
        }
    )
    return f"{BASE_URL}{query}"


def _get(url: str, key: str, timeout: int = 60) -> tuple[int, str]:
    """Return (status, body). Never raises."""
    req = urllib.request.Request(url, headers={"key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError) as exc:
        return -1, type(exc).__name__


def fetch(series: str, key: str) -> dict[str, float]:
    status, body = _get(_url(series), key)
    if status != 200 or not body:
        print(f"[{series}] fetch failed status={status}")
        return {}
    try:
        payload = json.loads(body)
    except ValueError:
        print(f"[{series}] response was not JSON")
        return {}

    out: dict[str, float] = {}
    for item in payload.get("items", []):
        raw_date = item.get("Tarih")
        if not raw_date:
            continue
        value = None
        for field, raw in item.items():
            if field in {"Tarih", "UNIXTIME"} or raw in (None, ""):
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
    out: dict[str, float] = {}
    for month, value in levels.items():
        year, _, mm = month.partition("-")
        base = levels.get(f"{int(year) - 1:04d}-{mm}")
        if base:
            out[month] = (value / base - 1.0) * 100.0
    return out


def main() -> int:
    key = os.environ.get("EVDS_API_KEY", "").strip()
    print("===== EVDS CANDIDATE SWEEP =====")
    print(f"baseline={BASELINE} start={START} end={_end()}")
    if not key:
        print("EVDS_API_KEY not set — skipping live sweep.")
        print("===== OTOMATIK KONTROL =====")
        print("RESULT: SKIP")
        return 0

    print("\n--- catalog endpoint probe (status codes only) ---")
    for path in CATALOG_PATHS:
        status, body = _get(f"{BASE_URL}{path}", key, timeout=30)
        head = body[:180].replace("\n", " ") if status == 200 else ""
        print(f"  {path}  -> status={status} head={head!r}")

    print("\n--- candidate series ---")
    base_levels = fetch(BASELINE, key)
    base_yoy = yoy(base_levels)
    if not base_yoy:
        print("baseline unavailable — cannot compare")
        print("===== OTOMATIK KONTROL =====")
        print("RESULT: FAIL (baseline fetch failed)")
        return 0

    rows: list[tuple[str, str, int, float, float]] = []
    for series in CANDIDATES:
        levels = fetch(series, key)
        months = sorted(levels)
        if not months:
            print(f"  {series:<18} obs=0 (unavailable)")
            continue
        cand_yoy = yoy(levels)
        overlap = sorted(set(cand_yoy) & set(base_yoy))
        if overlap:
            diffs = [abs(cand_yoy[m] - base_yoy[m]) for m in overlap]
            worst = max(diffs)
            mean = sum(diffs) / len(diffs)
        else:
            worst = mean = float("nan")
        newest = months[-1]
        rows.append((series, newest, len(overlap), mean, worst))
        print(
            f"  {series:<18} obs={len(months):<4} span={months[0]}..{newest} "
            f"overlap={len(overlap):<4} mean_diff={mean:7.3f}pp max_diff={worst:8.3f}pp"
        )

    winners = [
        r for r in rows
        if r[0] != BASELINE and r[1] >= LIVE_THRESHOLD and r[2] > 0 and r[4] <= TOLERANCE_PP
    ]

    print("\n--- verdict ---")
    print(f"live_threshold={LIVE_THRESHOLD} tolerance={TOLERANCE_PP}pp")
    print("===== OTOMATIK KONTROL =====")
    if winners:
        for series, newest, _, mean, worst in winners:
            print(f"candidate: {series} newest={newest} max_diff={worst:.4f}pp mean={mean:.4f}pp")
        print("RESULT: PASS (drop-in replacement found)")
    else:
        live = [r[0] for r in rows if r[1] >= LIVE_THRESHOLD]
        print(f"live_but_incompatible={live}")
        print("RESULT: FAIL (no drop-in replacement — swap requires a documented break)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
