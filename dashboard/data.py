"""Pure data-access layer for the dashboard.

Kept free of any Streamlit import so it is unit-testable in isolation and
reusable by other consumers. All queries are parameterized and run over a
read-only DuckDB connection — the dashboard can never mutate the warehouse.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

GOLD_TABLE = "mart_inflation_yoy"


def _connect(db_path: str) -> duckdb.DuckDBPyConnection:
    p = Path(db_path)
    if not p.exists():
        raise FileNotFoundError(f"warehouse not found: {db_path}")
    return duckdb.connect(str(p), read_only=True)


def list_items(db_path: str) -> list[str]:
    """Distinct item codes available in the gold mart, sorted."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            f"select distinct item_code from {GOLD_TABLE} order by 1"
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def load_inflation(
    db_path: str,
    item_codes: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Gold rows filtered by item codes and inclusive date range.

    Filters are bind parameters (never string-formatted into SQL).
    """
    sql = (
        "select obs_date, item_code, item_name, index_value, yoy_inflation_pct "
        f"from {GOLD_TABLE} where 1=1"
    )
    params: list[object] = []
    if item_codes:
        placeholders = ",".join("?" * len(item_codes))
        sql += f" and item_code in ({placeholders})"
        params.extend(item_codes)
    if start:
        sql += " and obs_date >= ?"
        params.append(start)
    if end:
        sql += " and obs_date <= ?"
        params.append(end)
    sql += " order by obs_date, item_code"

    con = _connect(db_path)
    try:
        return con.execute(sql, params).df()
    finally:
        con.close()


def latest_snapshot(db_path: str) -> pd.DataFrame:
    """Most recent observation per item (window function, one row per item)."""
    sql = f"""
        select obs_date, item_code, item_name, yoy_inflation_pct
        from (
            select *,
                   row_number() over (
                       partition by item_code order by obs_date desc
                   ) as rn
            from {GOLD_TABLE}
        )
        where rn = 1
        order by item_code
    """
    con = _connect(db_path)
    try:
        return con.execute(sql).df()
    finally:
        con.close()
