import boto3
from botocore.config import Config
from worker.settings import settings
def s3_client():
    return boto3.client("s3", endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key, aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region, config=Config(signature_version="s3v4"))
def get_object(key: str) -> bytes:
    return s3_client().get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()
def put_object(key: str, data: bytes, content_type: str="application/octet-stream"):
    s3_client().put_object(Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type)
