-- Daily turnover and revenue summary across all venues.
select
    bus_date,
    sum(turnover_sum)       as daily_turnover,
    sum(gmp_sum)            as daily_revenue,
    sum(games_played_sum)   as daily_games_played,
    count(distinct venue_code) as venues_reporting
from {{ ref('stg_egm_performance') }}
group by bus_date
order by bus_date
