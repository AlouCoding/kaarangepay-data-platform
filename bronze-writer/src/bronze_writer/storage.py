"""Object storage port (S3-compatible) and Parquet serialisation."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from bronze_writer.records import BRONZE_SCHEMA


class ObjectStore(Protocol):
    def ensure_bucket(self) -> None: ...

    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def list_keys(self, prefix: str = "") -> Iterator[str]: ...


def to_parquet(rows: list[dict[str, Any]]) -> bytes:
    """Rows -> Parquet bytes (zstd), with the fixed bronze schema."""
    table = pa.Table.from_pylist(rows, schema=BRONZE_SCHEMA)
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue()


class S3Store:
    """Any S3-compatible store (SeaweedFS here, AWS S3 in the cloud)."""

    def __init__(self, endpoint_url: str, bucket: str, access_key: str, secret_key: str) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 10, "mode": "standard"}),
        )

    def ensure_bucket(self) -> None:
        existing = {b["Name"] for b in self._s3.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self._s3.create_bucket(Bucket=self.bucket)

    def put(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        body = self._s3.get_object(Bucket=self.bucket, Key=key)["Body"]
        data: bytes = body.read()
        return data

    def list_keys(self, prefix: str = "") -> Iterator[str]:
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]
