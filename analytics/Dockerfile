# syntax=docker/dockerfile:1
# One image, two uses: `analytics pipeline` (load + dbt build + publish) and the Streamlit app.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DBT_PROJECT_DIR=/app/dbt DBT_TARGET_PATH=/tmp/dbt-target DBT_LOG_PATH=/tmp/dbt-logs DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    WAREHOUSE_PATH=/warehouse/kaarangepay.duckdb FEEDBACK_DB=/warehouse/fraud_feedback.sqlite

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/pip pip install . \
 && python -c "import kaarangepay_analytics, deltalake, duckdb, streamlit; print('analytics deps OK')"
COPY dbt ./dbt
COPY app ./app
COPY .streamlit ./.streamlit

# The warehouse volume is created from this folder the first time: it inherits its owner.
RUN useradd --create-home --uid 10001 analyst && mkdir -p /warehouse && chown analyst /warehouse
USER analyst

EXPOSE 8501
ENTRYPOINT ["analytics"]
CMD ["pipeline"]
