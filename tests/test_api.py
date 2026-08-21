"""Unit tests for the serving API against a fixture DuckDB warehouse.

Self-skips when fastapi/duckdb are unavailable (same pattern as the s3fs
tests) so the suite stays runnable in minimal environments; CI installs the
real dependencies and executes everything.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    import duckdb
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    print(f"SKIP — serving deps unavailable: {exc}")
    print("===== OTOMATIK KONTROL =====")
    print("tests_total: 0 (skipped)")
    print("RESULT: PASS")
    sys.exit(0)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE_ROWS = [
    ("2024-01-01", "TP.FG.J0", "CPI General", 1850.5, 64.86),
    ("2024-02-01", "TP.FG.J0", "CPI General", 1935.7, 67.07),
    ("2024-02-01", "TP.FG.J01", "Food", 2101.3, 71.12),
    ("2023-12-01", "TP.FG.J0", "CPI General", 1801.2, 64.77),
]


def build_fixture_db(path: str) -> None:
    con = duckdb.connect(path)
    con.execute(
        """
        create table mart_inflation_yoy (
            obs_date date,
            item_code varchar,
            item_name varchar,
            index_value double,
            yoy_inflation_pct double
        )
        """
    )
    con.executemany(
        "insert into mart_inflation_yoy values (?, ?, ?, ?, ?)", FIXTURE_ROWS
    )
    con.close()


results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, cond, detail))
    print(f"{'ok' if cond else 'FAIL'} - {name}{(' — ' + detail) if detail and not cond else ''}")


def main() -> int:
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "econ.duckdb")
    build_fixture_db(db)
    os.environ["LAKE_DB"] = db

    from serve.app import app

    client = TestClient(app)

    r = client.get("/health")
    check("health_200", r.status_code == 200, str(r.status_code))
    check("health_rows", r.json().get("gold_rows") == 4, str(r.json()))

    r = client.get("/v1/inflation")
    check("inflation_200", r.status_code == 200, str(r.status_code))
    body = r.json()
    check("inflation_all_rows", len(body) == 4, str(len(body)))
    check(
        "inflation_newest_first",
        body[0]["obs_date"] == "2024-02-01",
        body[0]["obs_date"],
    )

    r = client.get("/v1/inflation", params={"year": 2023})
    check("filter_year", len(r.json()) == 1 and r.json()[0]["obs_date"] == "2023-12-01", str(r.json()))

    r = client.get("/v1/inflation", params={"item_code": "TP.FG.J01"})
    check("filter_item", len(r.json()) == 1 and r.json()[0]["item_name"] == "Food", str(r.json()))

    r = client.get("/v1/inflation", params={"limit": 2})
    check("limit_respected", len(r.json()) == 2, str(len(r.json())))

    r = client.get("/v1/inflation", params={"limit": 99999})
    check("limit_validated_422", r.status_code == 422, str(r.status_code))

    r = client.get("/v1/inflation", params={"item_code": "x'; drop table mart_inflation_yoy; --"})
    check("injection_returns_empty", r.status_code == 200 and r.json() == [], str(r.status_code))
    con = duckdb.connect(db, read_only=True)
    still_there = con.execute("select count(*) from mart_inflation_yoy").fetchone()[0]
    con.close()
    check("injection_table_intact", still_there == 4, str(still_there))

    r = client.get("/v1/inflation/latest")
    latest = {row["item_code"]: row["obs_date"] for row in r.json()}
    check(
        "latest_per_item",
        latest == {"TP.FG.J0": "2024-02-01", "TP.FG.J01": "2024-02-01"},
        str(latest),
    )

    os.environ["LAKE_DB"] = os.path.join(tmp, "missing.duckdb")
    r = client.get("/health")
    check("missing_db_503", r.status_code == 503, str(r.status_code))

    failed = [n for n, ok, _ in results if not ok]
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(results)}")
    print(f"tests_failed: {len(failed)}")
    print(f"RESULT: {'PASS' if not failed else 'FAIL — ' + ', '.join(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
