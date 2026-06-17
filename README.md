# Gaming Data Pipeline — RAWG.io → Azure → Snowflake

An end-to-end data engineering pipeline that ingests video game data from the [RAWG.io](https://rawg.io/apidocs) API, lands it in Azure, transforms it through a medallion architecture in Snowflake, and validates every change automatically via GitHub Actions.

Built as a learning project to practice cloud data engineering: infrastructure-as-code, serverless ingestion, dbt transformations, and CI/CD.

## Architecture

```
RAWG.io API
     │
     ▼
Azure Function (Python, timer trigger, daily 02:00 UTC)
     │
     ├────────────────────────────┐
     ▼                            ▼
Azure Data Lake Gen2    Snowflake internal stage
(bronze archive)                  │
                                  ▼
                        Snowflake RAW schema  (COPY INTO)
                                  │
                                  ▼  dbt models
                        Snowflake STAGING schema (views, typed columns)
                                  │
                                  ▼  dbt models
                        Snowflake MART schema  (tables, analytics-ready)
```

Secrets (RAWG API key, Snowflake credentials) are never stored in code — the Function App pulls them at runtime from Azure Key Vault via its system-assigned managed identity.

## Tech stack

| Layer | Technology |
|---|---|
| Data source | RAWG.io REST API |
| Ingestion | Azure Functions (Python 3.11, timer trigger) |
| Storage | Azure Data Lake Storage Gen2 (bronze archive) |
| Secrets | Azure Key Vault (managed identity, no stored credentials) |
| Warehouse | Snowflake (RAW / STAGING / MART schemas) |
| Transformation | dbt Core, run via Docker |
| Infrastructure as Code | Bicep |
| CI | GitHub Actions |

## Repository structure

```
gaming-pipeline/
├── .github/workflows/       GitHub Actions CI pipelines
│   ├── bicep_validate.yml   Lints/validates Bicep on every push
│   ├── function_ci.yml      Lints + unit tests the Python ingestion code
│   └── dbt_ci.yml           Runs dbt compile/run/test against live Snowflake
├── infra/                   Bicep infrastructure-as-code
│   ├── main.bicep
│   ├── main.dev.bicepparam
│   └── modules/
│       ├── storage.bicep    ADLS Gen2 storage account + bronze container
│       ├── keyvault.bicep   Key Vault + RBAC role assignment
│       └── function.bicep   Function App with Key Vault-backed app settings
├── ingestion/                Azure Function — RAWG ingestion
│   ├── function_app.py      Timer-triggered entry point
│   ├── rawg_client.py       Paginated RAWG API client
│   ├── writer.py            Local JSONL writer (used for local dev/testing)
│   ├── main.py              Local-only runner (no Azure required)
│   └── tests/               Unit tests with mocked RAWG responses
└── transform/                dbt project
    ├── Dockerfile            Runs dbt inside a pinned Python 3.11 image
    ├── docker-compose.yml
    ├── dbt_project.yml
    ├── profiles.yml.example  Template — copy to ~/.dbt/profiles.yml locally
    └── models/
        ├── staging/          Typed views: stg_games, stg_genres, stg_platforms
        └── mart/              Analytics tables: mart_top_games, mart_genre_trends
```

## Data model

**RAW** (Snowflake, loaded via `COPY INTO`)
Untouched JSON in a single `VARIANT` column per table: `GAMES_RAW`, `GENRES_RAW`, `PLATFORMS_RAW`.

**STAGING** (dbt views)
Typed, cleaned columns parsed out of the raw JSON — `stg_games`, `stg_genres`, `stg_platforms`.

**MART** (dbt tables)
- `mart_top_games` — games ranked by a blended score (60% Metacritic, 40% user rating)
- `mart_genre_trends` — average rating and Metacritic score per genre, per release year (built using Snowflake's `LATERAL FLATTEN` to unnest each game's genre array)


## CI/CD

Every push triggers GitHub Actions, scoped to whichever part of the repo changed:

- **`bicep_validate.yml`** : compiles every Bicep file to catch syntax/type errors. Runs in plain GitHub-hosted runners; no cloud credentials needed.
- **`function_ci.yml`** : lints the Python ingestion code and runs unit tests against mocked RAWG responses. No real network calls.
- **`dbt_ci.yml`** : builds a `profiles.yml` from GitHub Secrets at runtime and runs `dbt compile → run → test → docs generate` against the real Snowflake warehouse. This is genuine end-to-end validation on every push.

### A deliberate limitation: deployment is manual

This repo's Azure tenant (a university student subscription) restricts application/service-principal registration in Entra ID, which is what GitHub Actions needs to authenticate to Azure non-interactively (whether via OIDC or a client secret). Without admin approval, GitHub Actions cannot deploy to Azure on this account.

As a result:
- **CI is fully automated** : every push validates infrastructure, code, and data transformations.
- **CD is manual** : deploying Bicep and publishing the Function App is done locally:

