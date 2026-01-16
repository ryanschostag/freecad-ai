import boto3
from botocore.config import Config
from datetime import datetime, timedelta, timezone
from app.settings import settings

def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )

def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    s3_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)

def presign_get(key: str, expires_seconds: int = 900):
    url = s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=expires_seconds,
    )
    return url, datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
