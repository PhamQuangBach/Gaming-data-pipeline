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