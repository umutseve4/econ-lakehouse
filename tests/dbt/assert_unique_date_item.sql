-- Data-quality gate: (obs_date, item_code) must be unique in silver.
select obs_date, item_code, count(*) as n
from {{ ref('stg_cpi') }}
group by 1, 2
having count(*) > 1
