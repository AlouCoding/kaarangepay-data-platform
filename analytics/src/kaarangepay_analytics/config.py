"""Settings read from the environment (Docker Compose sets them), with local defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    silver_root: str = field(default_factory=lambda: _env("SILVER_URI", "s3://silver"))
    gold_root: str = field(default_factory=lambda: _env("GOLD_URI", "s3://gold"))
    warehouse: Path = field(default_factory=lambda: Path(_env("WAREHOUSE_PATH", "/warehouse/kaarangepay.duckdb")))
    feedback_db: Path = field(default_factory=lambda: Path(_env("FEEDBACK_DB", "/warehouse/fraud_feedback.sqlite")))
    s3_endpoint: str = field(default_factory=lambda: _env("S3_ENDPOINT", "http://seaweedfs:8333"))
    s3_access_key: str = field(default_factory=lambda: _env("S3_ACCESS_KEY", "bronze"))
    s3_secret_key: str = field(default_factory=lambda: _env("S3_SECRET_KEY", "bronze-secret"))

    def storage_options(self, uri: str) -> dict[str, str] | None:
        """delta-rs options for an S3-compatible store (SeaweedFS): custom endpoint, plain HTTP, path-style."""
        if not uri.startswith("s3://"):
            return None
        return {
            "AWS_ENDPOINT_URL": self.s3_endpoint,
            "AWS_ACCESS_KEY_ID": self.s3_access_key,
            "AWS_SECRET_ACCESS_KEY": self.s3_secret_key,
            "AWS_REGION": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_VIRTUAL_HOSTED_STYLE_REQUEST": "false",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }
