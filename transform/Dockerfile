FROM python:3.11-slim

RUN pip install dbt-snowflake==1.8.0

WORKDIR /usr/app/dbt
COPY . .

ENTRYPOINT ["dbt"]