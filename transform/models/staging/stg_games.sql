WITH raw AS (
    SELECT raw_data
    FROM {{ source('raw', 'GAMES_RAW') }}
)

SELECT
    raw_data:id::INTEGER                          AS game_id,
    raw_data:name::STRING                         AS name,
    raw_data:slug::STRING                         AS slug,
    TRY_TO_DATE(raw_data:released::STRING)        AS released_date,
    raw_data:rating::FLOAT                        AS rating,
    raw_data:rating_top::INTEGER                  AS rating_top,
    raw_data:ratings_count::INTEGER               AS ratings_count,
    raw_data:metacritic::INTEGER                  AS metacritic_score,
    raw_data:playtime::INTEGER                    AS avg_playtime_hours,
    raw_data:suggestions_count::INTEGER           AS suggestions_count,
    raw_data:esrb_rating:name::STRING             AS esrb_rating,
    raw_data:background_image::STRING             AS background_image_url,
    raw_data:genres                               AS genres_raw,       -- keep array for bridge table
    raw_data:platforms                            AS platforms_raw,    -- keep array for bridge table
    CURRENT_TIMESTAMP()                           AS dbt_loaded_at
FROM raw
WHERE raw_data:id IS NOT NULL    -- filter out any malformed rows