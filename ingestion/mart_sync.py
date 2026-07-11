import os
import logging

import psycopg2
import psycopg2.extras
import snowflake.connector
from dotenv import load_dotenv

log = logging.getLogger(__name__)

# (postgres table name, snowflake MART table name, column order)
TABLES = [
    (
        "mart_top_games",
        "MART_TOP_GAMES",
        [
            "game_id", "name", "released_date", "release_year", "rating",
            "metacritic_score", "ratings_count", "avg_playtime_hours",
            "esrb_rating", "background_image_url", "combined_score",
            "overall_rank", "rank_in_year",
        ],
    ),
    (
        "mart_genre_trends",
        "MART_GENRE_TRENDS",
        [
            "genre_name", "release_year", "game_count", "avg_user_rating",
            "avg_metacritic", "best_rating", "worst_rating",
        ],
    ),
    (
        "mart_daily_release_counts",
        "MART_DAILY_RELEASE_COUNTS",
        [
            "released_date", "games_released", "avg_rating_that_day",
            "games_with_metacritic", "rolling_7day_release_count",
            "cumulative_release_count",
        ],
    ),
    (
        "mart_catalog_stats",
        "MART_CATALOG_STATS",
        [
            "total_games", "games_with_description", "games_with_rating",
            "games_with_metacritic", "avg_rating", "avg_metacritic",
        ],
    ),
]


def run_mart_sync(sf_conn=None, pg_conn=None) -> dict:
    own_sf = sf_conn is None
    own_pg = pg_conn is None

    try:
        if own_sf:
            sf_conn = snowflake.connector.connect(
                account=os.environ["SNOWFLAKE_ACCOUNT"],
                user=os.environ["SNOWFLAKE_USER"],
                password=os.environ["SNOWFLAKE_PASSWORD"],
                warehouse="GAMING_WH",
                database="GAMING_DB",
                schema="MART",
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

        counts = {}
        for pg_table, sf_table, columns in TABLES:
            rows = _fetch_snowflake_table(sf_conn, sf_table, columns)
            _replace_postgres_table(pg_conn, pg_table, columns, rows)
            counts[pg_table] = len(rows)
            log.info(f"Synced {pg_table}: {len(rows)} rows.")

        return {"status": "ok", "tables": counts}

    finally:
        if own_sf and sf_conn:
            sf_conn.close()
        if own_pg and pg_conn:
            pg_conn.close()


def _fetch_snowflake_table(sf_conn, table: str, columns: list[str]) -> list[tuple]:
    col_list = ", ".join(columns)
    cursor = sf_conn.cursor()
    cursor.execute(f"SELECT {col_list} FROM GAMING_DB.MART.{table}")
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _replace_postgres_table(pg_conn, table: str, columns: list[str], rows: list[tuple]) -> None:
    col_list = ", ".join(columns)
    with pg_conn.cursor() as cur:
        cur.execute(f"TRUNCATE {table}")
        if rows:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO {table} ({col_list}) VALUES %s",
                rows,
            )
    pg_conn.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    load_dotenv()
    result = run_mart_sync()
    print(result)