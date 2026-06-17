-- A moving count of how many games were released on each day.
-- One row per release day. Because the Function ingests exactly one day's
-- releases per run and appends to RAW, this table naturally accumulates a
-- full daily time series over time without needing a backfill.

WITH games AS (
    SELECT *
    FROM {{ ref('stg_games') }}
    WHERE released_date IS NOT NULL
),

daily_counts AS (
    SELECT
        released_date,
        COUNT(DISTINCT game_id)              AS games_released,
        ROUND(AVG(rating), 2)               AS avg_rating_that_day,
        COUNT(DISTINCT CASE WHEN metacritic_score IS NOT NULL THEN game_id END) AS games_with_metacritic
    FROM games
    GROUP BY released_date
)

SELECT
    released_date,
    games_released,
    avg_rating_that_day,
    games_with_metacritic,
    -- 7-day rolling sum: a smoothed view of release volume over the trailing week
    SUM(games_released) OVER (
        ORDER BY released_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                         AS rolling_7day_release_count,
    -- running total since the start of the data — "moving count" in the cumulative sense
    SUM(games_released) OVER (
        ORDER BY released_date
        ROWS UNBOUNDED PRECEDING
    )                                         AS cumulative_release_count
FROM daily_counts
ORDER BY released_date DESC
