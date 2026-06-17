WITH raw AS (
    SELECT raw_data, loaded_at
    FROM {{ source('raw', 'GENRES_RAW') }}
),
 
deduped AS (
    SELECT
        raw_data,
        ROW_NUMBER() OVER (
            PARTITION BY raw_data:id::INTEGER
            ORDER BY loaded_at DESC
        ) AS rn
    FROM raw
    WHERE raw_data:id IS NOT NULL
)
 
SELECT
    raw_data:id::INTEGER          AS genre_id,
    raw_data:name::STRING         AS name,
    raw_data:slug::STRING         AS slug,
    raw_data:games_count::INTEGER AS games_count
FROM deduped
WHERE rn = 1