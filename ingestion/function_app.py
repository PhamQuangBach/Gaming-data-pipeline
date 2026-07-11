import azure.functions as func
import logging
import os
import json
import tempfile
from datetime import date, datetime, timedelta
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import snowflake.connector
from rawg_client import fetch_games_released_on, fetch_genres, fetch_platforms, fetch_games_released_in_window, enrich_with_descriptions
import psycopg2
import voyageai


app = func.FunctionApp()
log = logging.getLogger(__name__)


@app.route(route="ingest_rawg", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ingest_rawg(req: func.HttpRequest) -> func.HttpResponse:
    try:
        result = _run_ingestion()
        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as e:
        log.error(f"Ingestion failed: {e}")
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(e)}),
            status_code=500,
            mimetype="application/json",
        )


def _run_ingestion() -> dict:
    """The actual ingestion logic, factored out so both the HTTP handler above
    and any future caller (tests, a CLI) can invoke it directly."""
    log.info(f"RAWG ingestion started at {datetime.utcnow().isoformat()}")

    api_key      = os.environ["RAWG_API_KEY"]
    release_date = date.today() - timedelta(days=1)   
    release_str  = release_date.isoformat()

    games     = fetch_games_released_in_window(api_key, end_date=release_date, window_days=7)
    genres    = fetch_genres(api_key)
    platforms = fetch_platforms(api_key)

    log.info(f"{len(games)} games released on {release_str}")
    if games:
        games = enrich_with_descriptions(api_key, games)

    try:
        adls_account = os.environ.get("ADLS_ACCOUNT_NAME")
        if adls_account:
            blob_client = BlobServiceClient(
                account_url=f"https://{adls_account}.blob.core.windows.net",
                credential=DefaultAzureCredential()
            )
            _upload_jsonl_adls(blob_client, games,     "bronze", f"games/{release_str}/data.jsonl")
            _upload_jsonl_adls(blob_client, genres,    "bronze", f"genres/{release_str}/data.jsonl")
            _upload_jsonl_adls(blob_client, platforms, "bronze", f"platforms/{release_str}/data.jsonl")
            log.info("ADLS upload complete.")
    except Exception as e:
        log.warning(f"ADLS upload failed (non-fatal): {e}")

    sf = _get_snowflake_connection()
    try:
        _load_to_snowflake(sf, games,     stage_path="games",     table="GAMES_RAW",     partition=release_str)
        _load_to_snowflake(sf, genres,    stage_path="genres",    table="GENRES_RAW",    partition=release_str)
        _load_to_snowflake(sf, platforms, stage_path="platforms", table="PLATFORMS_RAW", partition=release_str)
        log.info("Snowflake load complete.")
    finally:
        sf.close()

    log.info(
        f"Done — {len(games)} games released {release_str}, "
        f"{len(genres)} genres, {len(platforms)} platforms loaded into Snowflake."
    )

    return {
        "status": "success",
        "release_date": release_str,
        "games_loaded": len(games),
        "genres_loaded": len(genres),
        "platforms_loaded": len(platforms),
    }


def _load_to_snowflake(conn, records: list[dict], stage_path: str, table: str, partition: str) -> None:
    if not records:
        log.info(f"No records for {table} on {partition} — skipping load.")
        return

    remote_path = f"{stage_path}/{partition}/data.jsonl"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path = f.name

    cursor = conn.cursor()
    try:
        cursor.execute(
            f"PUT file://{tmp_path} @GAMING_DB.RAW.rawg_internal_stage/{remote_path} "
            f"AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        )
        log.info(f"PUT {len(records)} records → stage/{remote_path}")

        cursor.execute(f"""
            COPY INTO GAMING_DB.RAW.{table} (raw_data, loaded_at)
            FROM (
                SELECT $1, CURRENT_TIMESTAMP()
                FROM @GAMING_DB.RAW.rawg_internal_stage/{remote_path}
            )
            FILE_FORMAT = (TYPE = JSON)
            ON_ERROR = CONTINUE
        """)
        rows = cursor.fetchone()
        log.info(f"COPY INTO {table}: {rows}")
    finally:
        cursor.close()
        os.unlink(tmp_path)


def _get_snowflake_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse="GAMING_WH",
        database="GAMING_DB",
        schema="RAW",
    )


def _upload_jsonl_adls(blob_client, records, container, path):
    if not records:
        return
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob = blob_client.get_blob_client(container=container, blob=path)
    blob.upload_blob(content.encode("utf-8"), overwrite=True)
    log.info(f"ADLS: uploaded {len(records)} records → {container}/{path}")


# Public HTTP API
ALLOWED_QUERIES_PG = {
    "daily_release_counts": """
        SELECT released_date, games_released, rolling_7day_release_count, cumulative_release_count
        FROM mart_daily_release_counts
        ORDER BY released_date DESC
        LIMIT 90
    """,
    "genre_trends": """
        SELECT genre_name, release_year, game_count, avg_user_rating, avg_metacritic
        FROM mart_genre_trends
        ORDER BY release_year DESC, avg_user_rating DESC
        LIMIT 200
    """,
    "game_count": """
        SELECT total_games, games_with_description,
            games_with_rating, avg_rating,
            games_with_metacritic, avg_metacritic
        FROM mart_catalog_stats
    """,
    "top_games": """
        SELECT name, rating, metacritic_score, combined_score, overall_rank
        FROM mart_top_games
        ORDER BY overall_rank
        LIMIT 20
    """,
}

ALLOWED_QUERIES_SF = {
    "daily_release_counts": """
        SELECT released_date, games_released, rolling_7day_release_count, cumulative_release_count
        FROM GAMING_DB.MART.MART_DAILY_RELEASE_COUNTS
        ORDER BY released_date DESC
        LIMIT 90
    """,
    "genre_trends": """
        SELECT genre_name, release_year, game_count, avg_user_rating, avg_metacritic
        FROM GAMING_DB.MART.MART_GENRE_TRENDS
        ORDER BY release_year DESC, avg_user_rating DESC
        LIMIT 200
    """,
    "game_count": """
        SELECT total_games, games_with_description,
            games_with_rating, avg_rating,
            games_with_metacritic, avg_metacritic
        FROM GAMING_DB.MART.MART_CATALOG_STATS
    """,
    "top_games": """
        SELECT name, rating, metacritic_score, combined_score, overall_rank
        FROM GAMING_DB.MART.MART_TOP_GAMES
        ORDER BY overall_rank
        LIMIT 20
    """,
}


@app.route(route="games", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def get_games_data(req: func.HttpRequest) -> func.HttpResponse:
    cors_headers = _cors_headers()

    # Browser send an OPTIONS before the real GET
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers)

    report = req.params.get("report", "top_games")
    source = req.params.get("source", "postgres")
    query_set = ALLOWED_QUERIES_SF if source == "snowflake" else ALLOWED_QUERIES_PG

    if report not in query_set:
        return func.HttpResponse(
            json.dumps({
                "error": f"Unknown report '{report}'",
                "available_reports": list(query_set.keys())
            }),
            status_code=400,
            mimetype="application/json",
            headers=cors_headers,
        )

    try:
        conn = _get_reader_connection() if source == "snowflake" else _get_postgres_connection()
        cursor = conn.cursor()
        cursor.execute(query_set[report])

        columns = [col[0].lower() for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return func.HttpResponse(
            json.dumps({"report": report, "source": source, "row_count": len(rows), "data": rows}, default=str),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers,
        )

    except Exception as e:
        log.error(f"Error serving /games?report={report}&source={source}: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Internal server error"}),
            status_code=500,
            mimetype="application/json",
            headers=cors_headers,
        )


def _get_reader_connection():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_READER_USER"],
        password=os.environ["SNOWFLAKE_READER_PASSWORD"],
        warehouse="GAMING_WH",
        database="GAMING_DB",
        schema="MART",
    )


def _cors_headers() -> dict:
    origin = os.environ.get("ALLOWED_ORIGIN", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }



def _get_postgres_connection():
    """
    Connect to the pgvector Postgres instance.
    Credentials come from Key Vault via app settings, same pattern as
    Snowflake and RAWG. PG_HOST is the Flexible Server's FQDN from the
    Bicep deploy output.
    """
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=5432,
        dbname="gamesdb",
        user="gaming_app",
        password=os.environ["PG_PASSWORD"],
        sslmode="require",
        connect_timeout=10,
    )
 
 
def _get_voyage_client():
    return voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


@app.route(route="search", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def search_games(req: func.HttpRequest) -> func.HttpResponse:
    """
    Semantic search endpoint — the showcase piece for the portfolio demo.
 
    GET /api/search?q=open+world+fantasy+RPG
    GET /api/search?q=cozy+farming+sim&limit=5
 
    Flow:
      1. Embed the query text with Voyage AI (same model as the stored vectors)
      2. Run a pgvector cosine similarity search against the games table
      3. Return the top-N most semantically similar games as JSON
 
    This endpoint is what makes the portfolio demo interesting — a query like
    "sad story with beautiful music" returns games by meaning, not keyword
    matching, which only works because of the embedding pipeline we built.
 
    CORS-enabled for the same origin as get_games_data.
    No auth required — this is a public read-only endpoint.
    """
    cors_headers = _cors_headers()
 
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers)
 
    query = req.params.get("q", "").strip()
    if not query:
        return func.HttpResponse(
            json.dumps({"error": "Missing required parameter: q"}),
            status_code=400,
            mimetype="application/json",
            headers=cors_headers,
        )
 
    try:
        limit = min(int(req.params.get("limit", "10")), 20)  # cap at 20 results
    except ValueError:
        limit = 10
 
    try:
        # 1. Embed the query with Voyage AI
        # input_type="query" tells Voyage this is a search query, not a document —
        # it applies a different internal weighting that improves retrieval quality
        # compared to using "document" for both sides.
        voyage = _get_voyage_client()
        result = voyage.embed([query], model="voyage-4-lite", input_type="query")
        query_vector = result.embeddings[0]
 
        # 2. Similarity search via pgvector
        # <=> is the cosine distance operator — lower = more similar.
        # We ORDER BY distance ASC so the most similar games come first.
        # Only games with non-null embeddings are considered.
        pg = _get_postgres_connection()
        with pg.cursor() as cur:
            cur.execute(
                """
                SELECT
                    game_id,
                    name,
                    released_date,
                    rating,
                    metacritic_score,
                    LEFT(description_raw, 300) AS description_preview,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM games
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vector, query_vector, limit)
            )
            columns = [col[0] for col in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        pg.close()
 
        return func.HttpResponse(
            json.dumps({
                "query": query,
                "result_count": len(rows),
                "results": rows,
            }, default=str),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers,
        )
 
    except Exception as e:
        log.error(f"Search failed for query={query!r}: {e}")
        return func.HttpResponse(
            json.dumps({"error": "Search failed. Please try again."}),
            status_code=500,
            mimetype="application/json",
            headers=cors_headers,
        )