from datetime import datetime, timedelta
import os
 
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
import requests
 
 
default_args = {
    "owner": "gaming-pipeline",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}
 
 
def trigger_ingestion(**context):
    function_url = os.environ["AZURE_FUNCTION_URL"]
    function_key = os.environ["AZURE_FUNCTION_KEY"]
 
    response = requests.post(
        function_url,
        headers={"x-functions-key": function_key},
        timeout=300,  # ingestion can take a couple minutes depending on RAWG response size
    )
    response.raise_for_status()
 
    result = response.json()
    if result.get("status") != "success":
        raise RuntimeError(f"Ingestion did not report success: {result}")
 
    print(f"Ingestion succeeded: {result}")
    # Push to XCom so downstream tasks (or just the logs) can see what happened
    context["ti"].xcom_push(key="ingestion_result", value=result)
 
 
with DAG(
    dag_id="gaming_pipeline",
    description="Daily RAWG ingestion -> dbt transform -> test",
    default_args=default_args,
    schedule="0 3 * * *",   # 03:00 UTC — one hour after the old timer trigger time,
                            # giving headroom in case ingestion runs long
    start_date=datetime(2026, 6, 1),
    catchup=False,           # don't backfill every missed day if the DAG was paused
    tags=["gaming", "rawg", "snowflake", "dbt"],
) as dag:
 
    ingest = PythonOperator(
        task_id="ingest_rawg",
        python_callable=trigger_ingestion,
    )
 
    # dbt runs inside the same Docker image you already built for transform/.
    # Airflow has docker.sock mounted (see docker-compose.yml), so it can
    # launch a sibling container rather than needing dbt installed in the
    # Airflow image itself — keeps the two concerns separate.
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/airflow/transform && dbt run",
    )
 
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/airflow/transform && dbt test",
    )
 
    ingest >> dbt_run >> dbt_test