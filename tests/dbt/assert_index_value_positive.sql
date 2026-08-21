-- Data-quality gate: no CPI index value may be zero or negative.
-- dbt fails this test if any row is returned.
select *
from {{ ref('stg_cpi') }}
where index_value <= 0
