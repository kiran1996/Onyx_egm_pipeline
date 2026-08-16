{{
  config(
    unique_key=['bus_date', 'venue_code', 'egm_description', 'fp']
  )
}}

with source_data as (

    select *
    from {{ source('raw', 'egm_performance') }}

    {% if is_incremental() %}
    where ingested_at > (select coalesce(max(ingested_at), '1900-01-01'::timestamp) from {{ this }})
    {% endif %}

)

select
    cast(bus_date as date)              as bus_date,
    venue_code,
    egm_description,
    manufacturer,
    fp,
    cast(turnover_sum as numeric)       as turnover_sum,
    cast(gmp_sum as numeric)            as gmp_sum,
    cast(cast(games_played_sum as numeric) as bigint) as games_played_sum,
    ingested_at
from source_data
