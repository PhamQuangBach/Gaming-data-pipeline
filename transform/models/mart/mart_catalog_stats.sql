SELECT
    COUNT(*)                                              AS total_games,
    COUNT(description_raw)                                AS games_with_description,
    COUNT(rating)                                         AS games_with_rating,
    COUNT(metacritic_score)                               AS games_with_metacritic,
    ROUND(AVG(rating), 2)                                 AS avg_rating,
    ROUND(AVG(metacritic_score), 1)                       AS avg_metacritic
FROM {{ ref('stg_games') }}