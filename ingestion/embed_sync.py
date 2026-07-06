"""
embed_sync.py — incremental embedding sync for the weekly pipeline.

Reads games from Snowflake STAGING that have descriptions but no embedding
in Postgres yet, generates vectors via Voyage AI, and writes them to the
pgvector games table.

Designed to run automatically after dbt completes each week. New games
ingested that week get descriptions via the detail endpoint enrichment,
land in STAGING after dbt runs, and this script picks them up.

A typical weekly run touches only a handful of new games (single digits to
low double digits), so the Voyage AI free tier (200M tokens) is more than
sufficient indefinitely at this cadence.

Can also be run standalone:
    cd ingestion
    python embed_sync.py
"""
import os
import logging
import time

import psycopg2
import psycopg2.extras
import snowflake.connector
import voyageai
from dotenv import load_dotenv

log = logging.getLogger(__name__)

VOYAGE_MODEL = "voyage-4-lite"
BATCH_SIZE = 20
BATCH_PAUSE_SECONDS = 62


def run_embed_sync(
    sf_conn=None,
    pg_conn=None,
    voyage_client=None,
) -> dict:
    own_sf = sf_conn is None
    own_pg = pg_conn is None
    own_voyage = voyage_client is None

    try:
        if own_sf:
            sf_conn = snowflake.connector.connect(
                account=os.environ["SNOWFLAKE_ACCOUNT"],
                user=os.environ["SNOWFLAKE_USER"],
                password=os.environ["SNOWFLAKE_PASSWORD"],
                warehouse="GAMING_WH",
                database="GAMING_DB",
                schema="STAGING",
            )
        if own_pg:
            pg_conn = psycopg2.connect(
                host=os.environ["PG_HOST"],
                port=5432,
                dbname="gamesdb",
                user="gaming_app",
                password=os.environ["PG_PASSWORD"],
                sslmode="require",
                connect_timeout=10,
            )
        if own_voyage:
            voyage_client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


        new_games = _get_unembedded_games(sf_conn, pg_conn)

        if not new_games:
            log.info("Embedding sync: nothing to do — all games already embedded.")
            return {"status": "ok", "embedded": 0, "skipped": 0}

        log.info(f"Embedding sync: {len(new_games)} new games to embed.")


        _upsert_games(pg_conn, new_games)


        embedded = _embed_and_store(pg_conn, voyage_client, new_games)

        return {"status": "ok", "embedded": embedded, "skipped": 0}

    finally:
        if own_sf and sf_conn:
            sf_conn.close()
        if own_pg and pg_conn:
            pg_conn.close()


def _get_unembedded_games(sf_conn, pg_conn) -> list[dict]:

    with pg_conn.cursor() as cur:
        cur.execute("SELECT game_id FROM games WHERE embedding IS NOT NULL")
        already_embedded = {row[0] for row in cur.fetchall()}


    cursor = sf_conn.cursor()
    cursor.execute("""
        SELECT
            s.game_id,
            s.name,
            s.description_raw,
            s.released_date,
            s.rating,
            s.metacritic_score,
            LISTAGG(DISTINCT f.value:name::STRING, ', ')
                WITHIN GROUP (ORDER BY f.value:name::STRING) AS genres
        FROM GAMING_DB.STAGING.STG_GAMES s,
        LATERAL FLATTEN(input => s.genres_raw) f
        WHERE s.description_raw IS NOT NULL
          AND TRIM(s.description_raw) != ''
        GROUP BY s.game_id, s.name, s.description_raw,
                 s.released_date, s.rating, s.metacritic_score
    """)
    columns = [col[0].lower() for col in cursor.description]
    all_games = [dict(zip(columns, row)) for row in cursor.fetchall()]
    cursor.close()

    new_games = [g for g in all_games if g["game_id"] not in already_embedded]
    log.info(
        f"Snowflake has {len(all_games)} embeddable games, "
        f"{len(already_embedded)} already in Postgres, "
        f"{len(new_games)} new."
    )
    return new_games


def _upsert_games(pg_conn, games: list[dict]) -> None:
    with pg_conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO games (game_id, name, description_raw, released_date, rating, metacritic_score)
            VALUES %s
            ON CONFLICT (game_id) DO UPDATE SET
                name = EXCLUDED.name,
                description_raw = EXCLUDED.description_raw,
                released_date = EXCLUDED.released_date,
                rating = EXCLUDED.rating,
                metacritic_score = EXCLUDED.metacritic_score,
                synced_at = now()
            """,
            [(
                g["game_id"], g["name"], g.get("description_raw"),
                g.get("released_date"), g.get("rating"), g.get("metacritic_score"),
            ) for g in games],
        )
    pg_conn.commit()


def _build_embed_text(game: dict) -> str:
    parts = [game["name"]]
    if game.get("genres"):
        parts.append(game["genres"])
    if game.get("description_raw"):
        parts.append(game["description_raw"][:2000])
    return " | ".join(parts)


def _embed_and_store(pg_conn, voyage_client, games: list[dict]) -> int:
    total = len(games)
    embedded = 0

    for i in range(0, total, BATCH_SIZE):
        batch = games[i:i + BATCH_SIZE]
        texts = [_build_embed_text(g) for g in batch]

        log.info(f"Embedding batch {i // BATCH_SIZE + 1}: {len(batch)} games...")
        result = voyage_client.embed(texts, model=VOYAGE_MODEL, input_type="document")

        with pg_conn.cursor() as cur:
            for game, vector in zip(batch, result.embeddings):
                cur.execute(
                    "UPDATE games SET embedding = %s, embedded_at = now() WHERE game_id = %s",
                    (vector, game["game_id"])
                )
        pg_conn.commit()
        embedded += len(batch)
        log.info(f"  Stored {len(batch)} embeddings. Total: {embedded}/{total}")

        if i + BATCH_SIZE < total:
            time.sleep(BATCH_PAUSE_SECONDS)

    return embedded


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_dotenv()
    result = run_embed_sync()
    print(result)
