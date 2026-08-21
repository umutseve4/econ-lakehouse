"""Serving layer: read-only HTTP API over the gold mart.

Why an API and not a dashboard: the mart is a *data product*; an API is the
smallest contract other consumers (a notebook, a dashboard, a cron job) can
build on. The API never writes — the warehouse is opened read-only, so the
serving layer physically cannot corrupt what the pipeline produced.

Run locally:
    uvicorn serve.app:app --port 8000
    curl 'http://localhost:8000/v1/inflation?year=2024&limit=5'

The DuckDB file path comes from the LAKE_DB env var (default:
warehouse/econ.duckdb) so tests and CI can point it at a fixture.
"""

from __future__ import annotations

import os

import duckdb
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(
    title="econ-lakehouse serving API",
    description="Read-only access to the gold inflation mart (TCMB EVDS CPI).",
    version="0.6.0",
)

GOLD_TABLE = "mart_inflation_yoy"


def _connect() -> duckdb.DuckDBPyConnection:
    """Open the warehouse read-only. Fail loudly if the pipeline never ran."""
    db_path = os.environ.get("LAKE_DB", "warehouse/econ.duckdb")
    if not os.path.exists(db_path):
        raise HTTPException(
            status_code=503,
            detail=f"warehouse not found at {db_path!r} — run the pipeline first",
        )
    return duckdb.connect(db_path, read_only=True)


def _rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@app.get("/health")
def health() -> dict:
    con = _connect()
    try:
        n = con.execute(f"select count(*) from {GOLD_TABLE}").fetchone()[0]
    finally:
        con.close()
    return {"status": "ok", "gold_table": GOLD_TABLE, "gold_rows": n}


@app.get("/v1/inflation")
def inflation(
    year: int | None = Query(default=None, ge=1980, le=2100),
    item_code: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict]:
    """Rows from the gold mart, newest first. All filters are parameterized —
    user input never reaches the SQL string itself."""
    sql = f"select * from {GOLD_TABLE} where 1=1"
    params: list = []
    if year is not None:
        sql += " and extract(year from obs_date) = ?"
        params.append(year)
    if item_code is not None:
        sql += " and item_code = ?"
        params.append(item_code)
    sql += " order by obs_date desc, item_code limit ?"
    params.append(limit)

    con = _connect()
    try:
        cur = con.execute(sql, params)
        rows = _rows_to_dicts(cur)
    finally:
        con.close()
    for r in rows:
        r["obs_date"] = str(r["obs_date"])
    return rows


@app.get("/v1/inflation/latest")
def latest() -> list[dict]:
    """Most recent observation per item — the 'headline number' endpoint."""
    sql = f"""
        select * from {GOLD_TABLE}
        qualify row_number() over (
            partition by item_code order by obs_date desc
        ) = 1
        order by item_code
    """
    con = _connect()
    try:
        rows = _rows_to_dicts(con.execute(sql))
    finally:
        con.close()
    for r in rows:
        r["obs_date"] = str(r["obs_date"])
    return rows
