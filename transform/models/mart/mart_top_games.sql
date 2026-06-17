WITH games AS (
    SELECT * FROM {{ ref('stg_games') }}
    WHERE rating IS NOT NULL
      AND metacritic_score IS NOT NULL
),

scored AS (
    SELECT
        game_id,
        name,
        released_date,
        YEAR(released_date)                                      AS release_year,
        rating,
        metacritic_score,
        ratings_count,
        avg_playtime_hours,
        esrb_rating,
        background_image_url,
        -- Combined score: 60% metacritic (normalised to 0-5) + 40% user rating
        ROUND(
            (metacritic_score / 100.0 * 5 * 0.6) + (rating * 0.4),
        2)                                                       AS combined_score
    FROM games
)

SELECT
    *,
    RANK() OVER (ORDER BY combined_score DESC)        AS overall_rank,
    RANK() OVER (
        PARTITION BY release_year
        ORDER BY combined_score DESC
    )                                                 AS rank_in_year
FROM scored
ORDER BY overall_rank