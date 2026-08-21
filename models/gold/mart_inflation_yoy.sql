-- Gold: year-over-year inflation per item, the headline analytical mart.
-- YoY = (index_t / index_{t-12 months} - 1) * 100

with base as (
    select * from {{ ref('stg_cpi') }}
),

joined as (
    select
        cur.obs_date,
        cur.item_code,
        cur.item_name,
        cur.index_value,
        prev.index_value as index_value_prev_year
    from base as cur
    left join base as prev
        on  prev.item_code = cur.item_code
        and prev.obs_date  = cur.obs_date - interval 1 year
)

select
    obs_date,
    item_code,
    item_name,
    index_value,
    round((index_value / index_value_prev_year - 1) * 100, 2) as yoy_inflation_pct
from joined
where index_value_prev_year is not null
