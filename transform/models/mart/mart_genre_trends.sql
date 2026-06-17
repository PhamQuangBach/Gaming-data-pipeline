WITH games AS (
    SELECT * FROM {{ ref('stg_games') }}
    WHERE released_date IS NOT NULL
),

game_genres AS (
    SELECT
        g.game_id,
        g.name                          AS game_name,
        g.released_date,
        YEAR(g.released_date)           AS release_year,
        g.rating,
        g.metacritic_score,
        f.value:id::INTEGER             AS genre_id,
        f.value:name::STRING            AS genre_name
    FROM games g,
    LATERAL FLATTEN(input => g.genres_raw) f
)

SELECT
    genre_name,
    release_year,
    COUNT(DISTINCT game_id)             AS game_count,
    ROUND(AVG(rating), 2)              AS avg_user_rating,
    ROUND(AVG(metacritic_score), 1)    AS avg_metacritic,
    ROUND(MAX(rating), 2)              AS best_rating,
    ROUND(MIN(rating), 2)             AS worst_rating
FROM game_genres
WHERE genre_name IS NOT NULL
  AND release_year >= 2000
GROUP BY genre_name, release_year
ORDER BY release_year DESC, avg_user_rating DESC