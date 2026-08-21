-- Silver: typed, deduplicated staging view over the bronze Parquet lake.
-- Reads every year partition; bronze is append-only, silver enforces shape.
-- Provenance (source_name, fetched_at) flows through from bronze; on any
-- residual duplicate the most recently fetched row wins.

select
    cast(date as date)              as obs_date,
    cast(item_code as varchar)      as item_code,
    cast(item_name as varchar)      as item_name,
    cast(index_value as double)     as index_value,
    cast(source_name as varchar)    as source_name,
    cast(fetched_at as timestamptz) as fetched_at
from read_parquet('warehouse/bronze/cpi/year=*/data.parquet')
qualify row_number() over (
    partition by obs_date, item_code
    order by fetched_at desc
) = 1
