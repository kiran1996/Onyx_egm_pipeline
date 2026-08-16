-- Total turnover per venue, across the full history loaded so far.
select
    venue_code,
    sum(turnover_sum)       as total_turnover,
    sum(games_played_sum)   as total_games_played,
    count(distinct bus_date) as days_active
from {{ ref('stg_egm_performance') }}
group by venue_code
