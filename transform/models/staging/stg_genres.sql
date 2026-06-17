WITH raw AS (
    SELECT raw_data
    FROM {{ source('raw', 'GENRES_RAW') }}
)

SELECT
    raw_data:id::INTEGER      AS genre_id,
    raw_data:name::STRING     AS name,
    raw_data:slug::STRING     AS slug,
    raw_data:games_count::INTEGER AS games_count
FROM raw
WHERE raw_data:id IS NOT NULL