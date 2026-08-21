{% snapshot snap_cpi %}
{#
  Late-revision history for CPI observations.

  TCMB occasionally REVISES an already-published index value. Bronze keeps
  only the latest value per (obs_date, item_code) — incoming wins — so the
  old value would be lost. This dbt snapshot (SCD Type 2) closes the old
  version (dbt_valid_to set) and opens a new one whenever index_value
  changes, giving a full audit trail of revisions.

  strategy='check' on index_value only: a re-fetch of the SAME value with a
  newer fetched_at must NOT create a new version — only a real revision does.
#}
{{
    config(
      target_schema='snapshots',
      unique_key="obs_date || '|' || item_code",
      strategy='check',
      check_cols=['index_value'],
    )
}}

select
    obs_date,
    item_code,
    item_name,
    index_value,
    source_name,
    fetched_at
from {{ ref('stg_cpi') }}

{% endsnapshot %}
