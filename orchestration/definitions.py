"""Dagster Definitions: asset job + weekly schedule for the lakehouse.

Run the UI locally with:

    dagster dev -f orchestration/definitions.py

The schedule mirrors the CI cron (Monday 06:17 UTC) so both orchestration
paths rehearse the pipeline on the same cadence.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dagster import AssetSelection, Definitions, ScheduleDefinition, define_asset_job

from orchestration.assets import bronze_cpi, gold_nonempty, warehouse_marts

cpi_pipeline_job = define_asset_job(
    name="cpi_pipeline_job",
    selection=AssetSelection.all(),
    description="Full refresh: bronze ingest -> dbt silver/gold + checks.",
)

weekly_schedule = ScheduleDefinition(
    job=cpi_pipeline_job,
    cron_schedule="17 6 * * 1",
    name="weekly_cpi_refresh",
)

defs = Definitions(
    assets=[bronze_cpi, warehouse_marts],
    asset_checks=[gold_nonempty],
    jobs=[cpi_pipeline_job],
    schedules=[weekly_schedule],
)
