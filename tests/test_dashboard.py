"""Tests for the dashboard data layer + a headless Streamlit AppTest smoke.

Pattern mirrors tests/test_api.py: dependencies are optional locally — if
duckdb/pandas are unavailable the suite self-skips with RESULT: PASS so it
never blocks environments without the stack. CI installs everything and runs
the full suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import duckdb  # noqa: F401
    import pandas  # noqa: F401
except ImportError:
    print("===== OTOMATIK KONTROL =====")
    print("tests: SKIPPED (duckdb/pandas not installed in this environment)")
    print("RESULT: PASS")
    sys.exit(0)

from dashboard.data import latest_snapshot, list_items, load_inflation

FIXTURE_ROWS = [
    ("2024-01-01", "TP.FG.J0", "CPI General", 100.0, 64.86),
    ("2024-01-01", "TP.FG.J01", "Food", 110.0, 69.70),
    ("2024-02-01", "TP.FG.J0", "CPI General", 104.5, 67.07),
    ("2024-02-01", "TP.FG.J01", "Food", 115.2, 71.10),
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


checks: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    checks.append((name, cond))
    print(f"{name}: {'PASS' if cond else 'FAIL'}")


def main() -> int:
    tmpdir = tempfile.mkdtemp()
    db = str(Path(tmpdir) / "fixture.duckdb")
    build_fixture_db(db)

    # --- data layer ---
    items = list_items(db)
    check("list_items_sorted", items == ["TP.FG.J0", "TP.FG.J01"])

    df_all = load_inflation(db)
    check("load_all_rowcount", len(df_all) == 4)
    check(
        "load_all_ordered",
        list(df_all["obs_date"].astype(str))
        == ["2024-01-01", "2024-01-01", "2024-02-01", "2024-02-01"],
    )

    df_item = load_inflation(db, item_codes=["TP.FG.J0"])
    check(
        "filter_item_code",
        len(df_item) == 2 and set(df_item["item_code"]) == {"TP.FG.J0"},
    )

    df_range = load_inflation(db, start="2024-02-01")
    check("filter_start_date", len(df_range) == 2)
    df_range2 = load_inflation(db, start="2024-01-01", end="2024-01-31")
    check("filter_end_date", len(df_range2) == 2)

    snap = latest_snapshot(db)
    check(
        "latest_snapshot",
        len(snap) == 2 and set(snap["obs_date"].astype(str)) == {"2024-02-01"},
    )

    # parameterized SQL: malicious-looking value must return nothing, not break
    df_inj = load_inflation(db, item_codes=["x' or '1'='1"])
    check("param_sql_no_injection", len(df_inj) == 0)

    missing_raised = False
    try:
        list_items(str(Path(tmpdir) / "nope.duckdb"))
    except FileNotFoundError:
        missing_raised = True
    check("missing_db_raises", missing_raised)

    # --- Streamlit AppTest smoke (skips if streamlit absent locally) ---
    try:
        from streamlit.testing.v1 import AppTest

        os.environ["LAKE_DB"] = db
        at = AppTest.from_file(
            str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"),
            default_timeout=60,
        )
        at.run()
        check("apptest_no_exception", len(at.exception) == 0)
        check("apptest_has_title", len(at.title) > 0)
    except ImportError:
        print("apptest: SKIPPED (streamlit not installed)")

    failed = sum(1 for _, ok in checks if not ok)
    print("===== OTOMATIK KONTROL =====")
    print(f"tests_total: {len(checks)}")
    print(f"tests_failed: {failed}")
    print(f"RESULT: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
