# Gaming Data Pipeline

A cloud data pipeline that tracks video game releases, transforms the data through a medallion architecture, and exposes it through two public APIs: one for analytics and one for semantic search powered by vector embeddings.

Built as a learning project covering cloud data engineering, vector search, and AI-enabled data pipelines.

## What it does

Every week, the pipeline:

1. Fetches games released in the previous 7 days from RAWG.io
2. Archives the raw data in Azure Data Lake Storage and loads it into Snowflake
3. Transforms it with dbt into clean, typed, deduplicated tables
4. Generates vector embeddings for new games via Voyage AI and stores them in Postgres with pgvector
5. Makes the results available through public HTTP endpoints

The whole sequence runs automatically on a weekly schedule.

## Architecture

```
RAWG.io API
     │
     ▼
Azure Function (HTTP-triggered ingestion)
     │
     ├──────────────────────┐
     ▼                      ▼
Azure Data Lake Gen2    Snowflake
(raw archive,           RAW schema 
 30-day retention)           │
                             ▼  dbt (dedup + typed columns)
                        STAGING schema
                             │
                             ▼
                ┌────────────┴────────┐
                ▼                     ▼
             dbt (mart models)   Voyage AI
             MART schema         embeddings
                │                     │
                ▼                     ▼
           mart_sync.py       Postgres + pgvector
                │              (Azure Flexible Server)
                ▼                     │
       Postgres MART tables           │
       (mart_top_games, etc.)         │
                │                     │
                ▼                     ▼
       Azure Function          Azure Function
       /api/games              /api/search
       (analytics API,         (semantic search API)
        Postgres by default,
        Snowflake via
        ?source=snowflake)

```

The weekly schedule is owned by a GitHub Actions cron workflow. Apache Airflow runs locally as a development and learning environment with the same pipeline expressed as a DAG.

## Tech stack

| Layer | Technology |
|---|---|
| Data source | RAWG.io REST API |
| Ingestion | Azure Functions (Python) |
| Storage | Azure Data Lake Storage Gen2 |
| Secrets | Azure Key Vault  |
| Warehouse | Snowflake (RAW / STAGING / MART) |
| Transformation | dbt Core |
| Embeddings | Voyage AI (voyage-4-lite) |
| Vector store | Postgres 16 + pgvector (Azure Database for PostgreSQL Flexible Server) |
| Analytics API | Azure Functions (HTTP, CORS-scoped, read-only Snowflake user) |
| Search API | Azure Functions (HTTP, cosine similarity via pgvector) |
| Infrastructure as code | Bicep |
| Orchestration (local) | Apache Airflow (Docker) |
| Orchestration (production) | GitHub Actions scheduled workflow |
| CI | GitHub Actions |

## Repository structure

```
gaming-pipeline/
├── .github/workflows/
│   ├── bicep_validate.yml       Validates Bicep syntax on every push
│   ├── function_ci.yml          Lints and unit tests the Python ingestion code
│   ├── dbt_ci.yml               Runs dbt compile/run/test against live Snowflake
│   └── weekly_pipeline.yml      Production scheduler: ingest → dbt → test → embed sync + mart sync

├── infra/                       Bicep infrastructure-as-code
│   └── modules/
│       ├── storage.bicep        ADLS Gen2 + bronze container + 30-day lifecycle policy
│       ├── keyvault.bicep       Key Vault + RBAC role assignments
│       ├── function.bicep       Function App with Key Vault-backed app settings
│       └── pgvector.bicep       PostgreSQL Flexible Server + pgvector extension
├── ingestion/                   Azure Function app
│   ├── function_app.py          ingest_rawg, get_games_data, search_games endpoints
│   ├── rawg_client.py           RAWG API client with pagination, validation, enrichment
│   ├── embed_sync.py            Incremental embedding sync (new games → Voyage AI → Postgres)
│   ├── mart_sync.py             Full-refresh sync of dbt MART tables → Postgres
│   ├── writer.py                Local JSONL writer for dev/testing
│   └── tests/                   Unit tests with mocked API responses
├── transform/                   dbt project
│   └── models/
│       ├── staging/             stg_games, stg_genres, stg_platforms
│       └── mart/                mart_top_games, mart_genre_trends, mart_daily_release_counts
└── orchestration/               Airflow local dev environment
    └── dags/
        └── gaming_pipeline_dag.py   ingest → dbt run → dbt test → embed sync + mart sync

```

## Data model

**RAW**: untouched JSON from the RAWG API, loaded via `COPY INTO`. Includes `description_raw` fetched from the per-game detail endpoint during ingestion.

**STAGING**: typed, cleaned views built with dbt. A `ROW_NUMBER()` window function keeps only the most recently loaded version of each game, making the intentional redundancy of the 7-day rolling window fetch safe and clean.

**MART**: analytics-ready tables:
- `mart_top_games` — games ranked by a blended score of Metacritic (60%) and user rating (40%)
- `mart_genre_trends` — average rating and Metacritic score by genre and release year, built using Snowflake's `LATERAL FLATTEN` to unnest each game's genre array
- `mart_daily_release_counts` — daily release volume with a 7-day rolling count and a cumulative total

**Postgres (pgvector)** — a `games` table with a `VECTOR(1024)` column storing embeddings generated by Voyage AI's `voyage-4-lite` model. Fed from `STAGING.STG_GAMES`. Indexed with HNSW for approximate nearest-neighbor cosine similarity search.

Postgres also holds a full mirror of the 4 MART tables (`mart_top_games`, `mart_genre_trends`, `mart_daily_release_counts`, `mart_catalog_stats`), rebuilt from scratch on every pipeline run by `mart_sync.py`. This exists purely to make `/api/games` cheap and fast: Snowflake's warehouse auto-suspends between runs, so querying it live on every website hit meant paying a cold-start resume on unpredictable traffic. 


## APIs

Two public HTTP endpoints served by the Function App:

**Analytics**: `GET /api/games?report=<name>&source=<postgres|snowflake>`

Returns pre-computed data from the Snowflake MART schema. Reads from the Postgres mirror by default (`source=postgres`, fed by `mart_sync.py`), Snowflake is available as an explicit fallback via `source=snowflake` if the mirror is ever stale or unreachable. Available reports: `top_games`, `daily_release_counts`, `genre_trends`, `game_count`. Uses a fixed allow-list of queries for both sources.


**Semantic search**: `GET /api/search?q=<query>&limit=<n>`

Embeds the query text with Voyage AI (`input_type="query"`) and runs a cosine similarity search against the pgvector games table. Returns the top-N most semantically similar games with a `similarity` score. A query like *"open world fantasy RPG with a sad story"* returns games by meaning, not keyword matching.

Both endpoints use a read-only Snowflake account (`gaming_reader`) and are CORS-restricted to the configured portfolio domain.

## CI/CD

Every push runs:
- Bicep syntax validation
- Python lint and unit tests against mocked API responses
- dbt compile, run, and test against live Snowflake

The weekly production pipeline runs every Monday at 03:00 UTC via a scheduled GitHub Actions workflow: ingestion → dbt run → dbt test → embedding sync + MART sync.

Deploying changes to Azure infrastructure or Function code is done manually rather than through CI/CD, due to a service principal restriction on the Azure student subscription. Running the pipeline is fully automated; deploying changes to it is not.


## Possible next steps

- OIDC federated authentication for full automated CD
- Alerting on pipeline failures via Azure Monitor or a GitHub Actions failure webhook
- Frontend chart and search UI on the portfolio website
- Incremental dbt models as data volume grows
- Expanding the backfill to cover more genres and historical periods
