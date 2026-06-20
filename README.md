# Gaming Data Pipeline

A cloud data pipeline that tracks daily video game releases. It pulls data from the [RAWG.io](https://rawg.io/apidocs) API, lands it in Azure, transforms it through a medallion architecture in Snowflake, and exposes the results through a public read-only API for consumption by a website.

## What it does

Every day, the pipeline:

1. Fetches games released the previous day from RAWG.io, plus genre and platform lookup tables
2. Archives the raw data in Azure Data Lake Storage and loads it into Snowflake
3. Transforms it with dbt into clean, typed tables
4. Produces analytics-ready tables
5. Serves the results through a public API, ready for a frontend to consume

The whole sequence runs automatically on a daily schedule with no manual intervention.

## Architecture

```
RAWG.io API
     │
     ▼
Azure Function (ingestion)
     │
     ├────────────────────────┐
     ▼                        ▼
Azure Data Lake Gen2    Snowflake
(raw archive,           RAW schema
 30-day retention)      (COPY INTO)
                              │
                              ▼  dbt
                        STAGING schema
                        (typed, deduplicated)
                              │
                              ▼  dbt
                        MART schema
                        (analytics-ready)
                              │
                              ▼
                  Azure Function (public API)
                              │
                              ▼
                       Website (browser)
```

A scheduled GitHub Actions workflow triggers ingestion and runs the dbt transformations in sequence each day, stopping early if any step fails.

## Tech stack

| Layer | Technology |
|---|---|
| Data source | RAWG.io REST API |
| Ingestion | Azure Functions (Python) |
| Storage | Azure Data Lake Storage Gen2 |
| Secrets | Azure Key Vault |
| Warehouse | Snowflake |
| Transformation | dbt Core |
| Public API | Azure Functions (HTTP, CORS-scoped) |
| Infrastructure as code | Bicep |
| Orchestration & CI/CD | GitHub Actions, Apache Airflow |

## Repository structure

```
gaming-pipeline/
├── .github/workflows/      CI and the daily production schedule
├── infra/                  Bicep infrastructure-as-code
│   └── modules/            Storage, Key Vault, Function App
├── ingestion/              Azure Function: ingestion + public API
│   └── tests/              Unit tests with mocked API responses
├── transform/              dbt project
│   └── models/
│       ├── staging/        Typed, deduplicated views
│       └── mart/           Analytics-ready tables
└── orchestration/          Airflow setup for local development
```

## Data model

**RAW** : untouched JSON from the API, loaded as-is into Snowflake.

**STAGING** : typed, cleaned views built with dbt. Deduplication happens here, keeping the most recently loaded version of each record.

**MART** : analytics-ready tables:
- `mart_genre_trends` : average rating and Metacritic score by genre and release year
- `mart_daily_release_counts` : daily release volume, with a 7-day rolling count and a cumulative total

## Public API

A read-only HTTP endpoint serves pre-approved reports from the MART schema:

```
GET /api/games?report=daily_release_counts
GET /api/games?report=genre_trends
```

## CI/CD

Every push runs the relevant checks automatically:

- Bicep files are validated for syntax and type errors
- Python ingestion code is linted and unit tested against mocked API responses
- dbt models are compiled, run, and tested against the live Snowflake warehouse

A separate scheduled workflow runs the production pipeline daily: triggering ingestion, then running dbt, then running dbt tests, stopping the sequence if any step fails.

Deploying changes to the Azure infrastructure or Function code is done manually rather than through CI/CD, due to a permissions restriction on the Azure subscription this project runs on. Running the pipeline day-to-day is fully automated; deploying *changes* to it is not.

## Security

- No secrets are committed to the repository
- The Function App uses a system-assigned managed identity to read secrets from Key Vault
- Separate, least-privilege Snowflake accounts are used for writing data and for serving the public API, so the public-facing endpoint has no write access to anything
- Raw data in Azure Storage is automatically deleted after 30 days via a lifecycle policy

## Possible next steps

- Federated authentication so CI/CD can deploy infrastructure changes directly
- Alerting on pipeline failures
- A chart or dashboard on the website consuming the public API
- Incremental dbt models as data volume grows
- Broader data quality testing, including freshness checks
