"""Offline unit tests for the EVDS client (no network, no API key).

Run: python tests/test_evds_client.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.evds_client import EvdsError, build_url, parse_response  # noqa: E402
from ingest.ingest import validate  # noqa: E402

FIXTURE = {
    "totalCount": 4,
    "items": [
        {"Tarih": "2020-1", "TP_FG_J0": "440.50", "UNIXTIME": {"$numberLong": "1577836800"}},
        {"Tarih": "2020-2", "TP_FG_J0": "442.10", "UNIXTIME": {"$numberLong": "1580515200"}},
        {"Tarih": "2020-3", "TP_FG_J0": None, "UNIXTIME": {"$numberLong": "1583020800"}},
        {"Tarih": "2020-12", "TP_FG_J0": "475.99", "UNIXTIME": {"$numberLong": "1606780800"}},
    ],
}


def test_build_url() -> None:
    url = build_url("TP.FG.J0", "01-01-2020", "01-08-2026")
    assert url.startswith("https://evds3.tcmb.gov.tr/service/evds/series=TP.FG.J0")
    assert "startDate=01-01-2020" in url and "endDate=01-08-2026" in url
    assert "type=json" in url
    assert "key=" not in url, "API key must travel in the header, never the URL"


def test_parse_maps_to_bronze_contract() -> None:
    df = parse_response(FIXTURE, "TP.FG.J0")
    assert list(df.columns) == ["date", "item_code", "item_name", "index_value"]
    assert len(df) == 3, "null observation must be dropped"
    assert df["date"].tolist() == ["2020-01-01", "2020-02-01", "2020-12-01"]
    assert df["item_code"].unique().tolist() == ["CP00"]
    assert abs(df["index_value"].iloc[0] - 440.50) < 1e-9


def test_parse_output_passes_bronze_validation() -> None:
    df = parse_response(FIXTURE, "TP.FG.J0")
    validated = validate(df)  # must not raise
    assert len(validated) == 3


def test_parse_empty_response_fails() -> None:
    try:
        parse_response({"items": []}, "TP.FG.J0")
    except EvdsError:
        pass
    else:
        raise AssertionError("empty response must raise EvdsError")


def test_parse_all_null_fails() -> None:
    payload = {"items": [{"Tarih": "2020-1", "TP_FG_J0": None}]}
    try:
        parse_response(payload, "TP.FG.J0")
    except EvdsError:
        pass
    else:
        raise AssertionError("all-null series must raise EvdsError")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"{t.__name__}: PASS")
        except AssertionError as exc:
            failed += 1
            print(f"{t.__name__}: FAIL — {exc}")
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(tests)}")
    print(f"tests_failed: {failed}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
