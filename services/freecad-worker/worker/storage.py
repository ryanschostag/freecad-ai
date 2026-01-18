"""Artifact storage helpers.

In production we store artifacts in an S3-compatible object store (MinIO/AWS S3).
For the docker "test" profile we want deterministic, self-contained runs that do
not require valid external credentials. In that mode we can store artifacts on
the container filesystem.
"""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.config import Config

from worker.settings import settings


def _artifact_root() -> Path:
    return Path(settings.artifact_dir).resolve()


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def get_object(key: str) -> bytes:
    if settings.storage_backend.lower() == "local":
        path = _artifact_root() / key
        return path.read_bytes()
    return s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    # content_type is unused for the local backend, but we keep the signature
    # identical to the S3 backend.
    if settings.storage_backend.lower() == "local":
        root = _artifact_root()
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return

    s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
