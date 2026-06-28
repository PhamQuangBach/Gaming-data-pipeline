import azure.functions as func
import logging
import os
import json
import tempfile
from datetime import date, datetime, timedelta
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import snowflake.connector
from rawg_client import fetch_games_released_on, fetch_genres, fetch_platforms, fetch_games_released_in_window

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
ALLOWED_QUERIES = {
    "top_games": """
        SELECT name, rating, metacritic_score, combined_score, overall_rank
        FROM GAMING_DB.MART.MART_TOP_GAMES
        ORDER BY overall_rank
        LIMIT 50
    """,
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
}


@app.route(route="games", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def get_games_data(req: func.HttpRequest) -> func.HttpResponse:
    """
    GET /api/games?report=top_games
    GET /api/games?report=daily_release_counts
    GET /api/games?report=genre_trends
    """
    cors_headers = _cors_headers()

    # Browser send an OPTIONS before the real GET
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers)

    report = req.params.get("report", "top_games")

    if report not in ALLOWED_QUERIES:
        return func.HttpResponse(
            json.dumps({
                "error": f"Unknown report '{report}'",
                "available_reports": list(ALLOWED_QUERIES.keys())
            }),
            status_code=400,
            mimetype="application/json",
            headers=cors_headers,
        )

    try:
        conn = _get_reader_connection()
        cursor = conn.cursor()
        cursor.execute(ALLOWED_QUERIES[report])

        columns = [col[0].lower() for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        return func.HttpResponse(
            json.dumps({"report": report, "row_count": len(rows), "data": rows}, default=str),
            status_code=200,
            mimetype="application/json",
            headers=cors_headers,
        )

    except Exception as e:
        log.error(f"Error serving /games?report={report}: {e}")
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