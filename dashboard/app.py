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

from dashboard.bootstrap import ensure_warehouse, read_provenance  # noqa: E402
from dashboard.data import latest_snapshot, list_items, load_inflation  # noqa: E402

DB_PATH = os.environ.get("LAKE_DB", "warehouse/econ.duckdb")

# Streamlit Cloud passes the EVDS key via app secrets, not env vars — copy it
# over so orchestrate.py (a plain subprocess) can see it. Guarded because
# st.secrets raises when no secrets.toml exists (e.g. local runs, CI).
try:
    if "EVDS_API_KEY" in st.secrets and not os.environ.get("EVDS_API_KEY"):
        os.environ["EVDS_API_KEY"] = st.secrets["EVDS_API_KEY"]
except Exception:
    pass

st.set_page_config(page_title="econ-lakehouse — CPI dashboard", layout="wide")
st.title("Türkiye CPI — Year-over-Year Inflation")
st.caption(f"Source: gold mart `mart_inflation_yoy` · warehouse: `{DB_PATH}`")

# Cold start (fresh container / Streamlit Cloud): build the warehouse once
# through the same single-entrypoint pipeline used by Docker and CI. The
# bootstrap is provenance-aware: a stale fixture warehouse is rebuilt live
# automatically once the EVDS_API_KEY secret becomes available.
try:
    with st.spinner("Preparing the warehouse (first start may take a minute)..."):
        boot_mode = ensure_warehouse(DB_PATH)
except RuntimeError as exc:
    st.error(f"Pipeline bootstrap failed: {exc}")
    st.stop()

# The banner must reflect what is IN the warehouse, not what happened during
# this particular boot: Streamlit reruns the script constantly, and on every
# rerun after the first the warehouse already exists. Persisted provenance
# (written by orchestrate.py) is the durable source of truth.
prov = read_provenance(DB_PATH)
prov_mode = (prov or {}).get("mode")

if prov_mode == "fixture" or (prov is None and boot_mode == "built-fixture"):
    st.warning(
        "⚠️ Running on the **synthetic fixture dataset** (no EVDS_API_KEY "
        "configured). Numbers below are NOT real TCMB/TÜİK data."
    )
elif prov_mode == "live":
    st.caption(
        f"✅ Live EVDS data · source `{prov.get('source_name', '?')}` · "
        f"built {prov.get('built_at_utc', '?')} UTC"
    )

if boot_mode == "rebuilt-live":
    st.info(
        "♻️ The previous warehouse was built from the synthetic fixture; "
        "it has been rebuilt automatically with live EVDS data."
    )

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
