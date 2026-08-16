-- Total revenue (gmp_sum) aggregated by EGM within each venue.
select
    venue_code,
    egm_description,
    manufacturer,
    sum(gmp_sum)            as total_revenue,
    sum(turnover_sum)       as total_turnover,
    sum(games_played_sum)   as total_games_played
from {{ ref('stg_egm_performance') }}
group by venue_code, egm_description, manufacturer
