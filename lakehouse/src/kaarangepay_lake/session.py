"""SparkSession wired for Delta Lake and an S3-compatible store (SeaweedFS locally)."""

from __future__ import annotations

import os

from pyspark.sql import SparkSession


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def lake_session(app_name: str) -> SparkSession:
    endpoint = env("S3_ENDPOINT", "http://seaweedfs:8333")
    builder = (
        SparkSession.builder.appName(app_name)
        # Delta Lake: ACID tables made of Parquet files + a transaction log (_delta_log/)
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        # S3A: Hadoop's S3 client, pointed at SeaweedFS with path-style URLs
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.hadoop.fs.s3a.endpoint", endpoint)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", str(endpoint.startswith("https")).lower())
        .config("spark.hadoop.fs.s3a.aws.credentials.provider",
                "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider")
        .config("spark.hadoop.fs.s3a.access.key", env("S3_ACCESS_KEY", "bronze"))
        .config("spark.hadoop.fs.s3a.secret.key", env("S3_SECRET_KEY", "bronze-secret"))
        # Small local machine: few shuffle partitions, all timestamps in UTC
        .config("spark.sql.shuffle.partitions", env("SPARK_SHUFFLE_PARTITIONS", "8"))
        .config("spark.sql.session.timeZone", "UTC")
    )
    return builder.getOrCreate()


def ensure_bucket(bucket: str) -> None:
    """S3A cannot create buckets: do it with boto3 before Spark writes there."""
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=env("S3_ENDPOINT", "http://seaweedfs:8333"),
        aws_access_key_id=env("S3_ACCESS_KEY", "bronze"),
        aws_secret_access_key=env("S3_SECRET_KEY", "bronze-secret"),
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}),
    )
    existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        s3.create_bucket(Bucket=bucket)
