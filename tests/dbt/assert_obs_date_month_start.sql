-- Data-quality gate: CPI frequency is monthly, so obs_date must be first of month.
select *
from {{ ref('stg_cpi') }}
where date_part('day', obs_date) <> 1
