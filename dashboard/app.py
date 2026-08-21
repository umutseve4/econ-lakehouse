"""Streamlit dashboard: Turkish CPI year-over-year inflation from the gold mart.

Run locally (after the pipeline has built the warehouse):

    streamlit run dashboard/app.py

The app is a thin presentation layer: every query lives in dashboard/data.py
(read-only, parameterized). Warehouse path comes from LAKE_DB, defaulting to
warehouse/econ.duckdb — same convention as the serving API.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.data import latest_snapshot, list_items, load_inflation  # noqa: E402

DB_PATH = os.environ.get("LAKE_DB", "warehouse/econ.duckdb")

st.set_page_config(page_title="econ-lakehouse — CPI dashboard", layout="wide")
st.title("Türkiye CPI — Year-over-Year Inflation")
st.caption(f"Source: gold mart `mart_inflation_yoy` · warehouse: `{DB_PATH}`")

if not Path(DB_PATH).exists():
    st.error(
        f"Warehouse not found at `{DB_PATH}`. "
        "Run the pipeline first (python orchestrate.py) or set LAKE_DB."
    )
    st.stop()

items = list_items(DB_PATH)
if not items:
    st.warning("Gold mart is empty — nothing to display.")
    st.stop()

selected = st.sidebar.multiselect("Item codes", options=items, default=items)

df = load_inflation(DB_PATH, item_codes=selected or None)
latest = latest_snapshot(DB_PATH)
if selected:
    latest = latest[latest["item_code"].isin(selected)]

st.subheader("Latest observation per item")
if len(latest) > 0:
    cols = st.columns(len(latest))
    for col, (_, row) in zip(cols, latest.iterrows()):
        col.metric(
            label=f"{row['item_code']} ({row['obs_date']})",
            value=f"{row['yoy_inflation_pct']:.2f}%",
        )
else:
    st.info("No items selected.")

st.subheader("YoY inflation over time")
if len(df) > 0:
    chart_df = df.pivot(
        index="obs_date", columns="item_code", values="yoy_inflation_pct"
    )
    st.line_chart(chart_df)

    st.subheader("Underlying data")
    st.dataframe(df, use_container_width=True)
    st.download_button(
        "Download CSV",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name="inflation_yoy.csv",
        mime="text/csv",
    )
else:
    st.info("No rows match the current filters.")
