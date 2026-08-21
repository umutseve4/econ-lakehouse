"""EVDS (TCMB) client: fetch real CPI series -> bronze-contract CSV.

Usage:
    EVDS_API_KEY=... python ingest/evds_client.py \
        --series TP.FG.J0 --start 2020-01 --out data/evds/cpi_evds.csv

The API key is read ONLY from the EVDS_API_KEY environment variable.
Never hardcode it. Parsing is separated from fetching so it can be
unit-tested offline. Exit code 0 = PASS, 1 = FAIL.

EVDS docs: https://evds2.tcmb.gov.tr/help/videos/EVDS_Web_Service_Usage_Guide.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

# TCMB migrated EVDS from evds2 to evds3; evds2 302-redirects every request
# (including API paths) to the evds3 SPA homepage, returning HTML instead of
# JSON. Verified by CI diagnostic matrix on 2026-08-21 (PR #3, run #8).
BASE_URL = "https://evds3.tcmb.gov.tr/service/evds/"

# EVDS series -> human-readable item metadata (bronze contract fields)
SERIES_META = {
    "TP.FG.J0": ("CP00", "CPI all items (2003=100)"),
}


class EvdsError(Exception):
    pass


def build_url(series: str, start: str, end: str) -> str:
    """Build the EVDS REST URL. Dates are DD-MM-YYYY per EVDS convention."""
    return (
        f"{BASE_URL}series={series}"
        f"&startDate={start}&endDate={end}"
        f"&type=json&frequency=5&aggregationTypes=avg&formulas=0"
    )


def parse_response(payload: dict, series: str) -> pd.DataFrame:
    """EVDS JSON -> bronze-contract DataFrame (date, item_code, item_name, index_value).

    EVDS monthly dates arrive as 'YYYY-M' (e.g. '2020-1'); values may be
    strings or null. Null observations are dropped, not silently zeroed.
    """
    items = payload.get("items")
    if not items:
        raise EvdsError("empty EVDS response (no 'items')")

    field = series.replace(".", "_")
    code, name = SERIES_META.get(series, (series, series))

    rows = []
    for it in items:
        raw = it.get(field)
        if raw is None or raw == "":
            continue
        year, month = it["Tarih"].split("-")
        rows.append(
            {
                "date": f"{int(year):04d}-{int(month):02d}-01",
                "item_code": code,
                "item_name": name,
                "index_value": float(raw),
            }
        )
    if not rows:
        raise EvdsError(f"no non-null observations for {series}")
    return pd.DataFrame(rows)


def fetch(series: str, start_ym: str, api_key: str) -> pd.DataFrame:
    """Fetch a monthly series from EVDS from start_ym (YYYY-MM) to today."""
    y, m = start_ym.split("-")
    start = f"01-{int(m):02d}-{y}"
    today = date.today()
    end = f"01-{today.month:02d}-{today.year}"

    headers = {
        "key": api_key,
        "User-Agent": "Mozilla/5.0 (compatible; econ-lakehouse-pipeline/1.0)",
        "Accept": "application/json",
    }
    req = urllib.request.Request(build_url(series, start, end), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        status = getattr(resp, "status", "?")
        body = resp.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise EvdsError(
            f"non-JSON response (HTTP {status}): {body[:200]!r}"
        ) from exc
    return parse_response(payload, series)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", default="TP.FG.J0")
    parser.add_argument("--start", default="2015-01")
    parser.add_argument("--out", default="data/evds/cpi_evds.csv")
    args = parser.parse_args()

    checks: list[tuple[str, str]] = []
    try:
        api_key = os.environ.get("EVDS_API_KEY", "")
        if not api_key:
            raise EvdsError("EVDS_API_KEY env var is not set")
        checks.append(("api_key_present", "PASS"))

        df = fetch(args.series, args.start, api_key)
        checks.append(("fetch_and_parse", f"PASS ({len(df)} rows)"))

        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        checks.append(("write_csv", f"PASS ({out})"))
        status = 0
    except (EvdsError, OSError, KeyError, ValueError) as exc:
        checks.append(("pipeline", f"FAIL — {exc}"))
        status = 1

    print("===== OTOMATIK KONTROL =====")
    for name, result in checks:
        print(f"{name}: {result}")
    print(f"RESULT: {'PASS' if status == 0 else 'FAIL'}")
    return status


if __name__ == "__main__":
    sys.exit(main())
