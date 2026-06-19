import azure.functions as func
import logging
import os
import json
import tempfile
from datetime import date, datetime, timedelta
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
import snowflake.connector
from rawg_client import fetch_games_released_on, fetch_games, fetch_genres, fetch_platforms

app = func.FunctionApp()
log = logging.getLogger(__name__)


@app.timer_trigger(
    schedule="0 0 2 * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True
)
def ingest_rawg(timer: func.TimerRequest) -> None:
    if timer.past_due:
        log.warning("Timer is past due — running now anyway.")

    log.info(f"RAWG ingestion started at {datetime.utcnow().isoformat()}")

    api_key   = os.environ["RAWG_API_KEY"]
    today     = date.today().isoformat()

    release_date = date.today() - timedelta(days=1)   # "yesterday" — the day that just fully elapsed
    release_str  = release_date.isoformat()

    # Fetch Games from source
    games     = fetch_games_released_on(api_key, target_date=release_date)
    genres    = fetch_genres(api_key)
    platforms = fetch_platforms(api_key)

    # Upload to ADLS
    try:
        adls_account = os.environ.get("ADLS_ACCOUNT_NAME")
        if adls_account:
            blob_client = BlobServiceClient(
                account_url=f"https://{adls_account}.blob.core.windows.net",
                credential=DefaultAzureCredential()
            )
            _upload_jsonl_adls(blob_client, games,     "bronze", f"games/{today}/data.jsonl")
            _upload_jsonl_adls(blob_client, genres,    "bronze", f"genres/{today}/data.jsonl")
            _upload_jsonl_adls(blob_client, platforms, "bronze", f"platforms/{today}/data.jsonl")
            log.info("ADLS upload complete.")
    except Exception as e:
        log.warning(f"ADLS upload failed (non-fatal): {e}")

    # Upload to Snowflake
    sf = _get_snowflake_connection()
    try:
        _load_to_snowflake(sf, games,     stage_path="games",     table="GAMES_RAW")
        _load_to_snowflake(sf, genres,    stage_path="genres",    table="GENRES_RAW")
        _load_to_snowflake(sf, platforms, stage_path="platforms", table="PLATFORMS_RAW")
        log.info("Snowflake load complete.")
    finally:
        sf.close()

    log.info(
        f"Done — {len(games)} games released {release_str}, "
        f"{len(genres)} genres, {len(platforms)} platforms loaded into Snowflake."
    )


def _load_to_snowflake(conn, records: list[dict], stage_path: str, table: str) -> None:
    # Write a temp file
    today = date.today().isoformat()
    remote_path = f"{stage_path}/{today}/data.jsonl"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp_path = f.name

    cursor = conn.cursor()
    try:
        # Upload the temp file to Snowflake
        cursor.execute(
            f"PUT file://{tmp_path} @GAMING_DB.RAW.rawg_internal_stage/{remote_path} "
            f"AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        )
        log.info(f"PUT {len(records)} records → stage/{remote_path}")

        # Copy data from temp file to Database 
        cursor.execute(f"""
            COPY INTO GAMING_DB.RAW.{table} (raw_data)
            FROM (
                SELECT $1
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
        LIMIT 500
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
 
    # Browsers send an OPTIONS first before the real GET
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
    """
    Connect using the gaming_reader user
    """
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_READER_USER"],
        password=os.environ["SNOWFLAKE_READER_PASSWORD"],
        warehouse="GAMING_WH",
        database="GAMING_DB",
        schema="MART",
    )
 
 
def _cors_headers() -> dict:
    """
    Only the configured origin(s) may call this API from browser JS
    """
    origin = os.environ.get("ALLOWED_ORIGIN", "*")
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
    }
 