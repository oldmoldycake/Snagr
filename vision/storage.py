"""The only S3 client in the project (D-V3): image bytes in and out of the
object store, keyed by their sha256 content hash (D-V12 — duplicate photos
store once). Everything else (backend, frontend) reaches bytes through this
service's /images endpoint, never the store itself."""

import boto3
from botocore.exceptions import ClientError
from config import S3_ACCESS_KEY, S3_BUCKET, S3_ENDPOINT, S3_SECRET_KEY


class Storage:
    """Thin wrapper over one bucket; keys are sha256 hex digests."""

    def __init__(self) -> None:
        self._s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist yet (first start)."""
        try:
            self._s3.head_bucket(Bucket=S3_BUCKET)
        except ClientError:
            self._s3.create_bucket(Bucket=S3_BUCKET)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        """The object's (bytes, content_type), or None when the key is absent."""
        try:
            obj = self._s3.get_object(Bucket=S3_BUCKET, Key=key)
        except ClientError:
            return None
        return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=S3_BUCKET, Key=key)
        except ClientError:
            return False
        return True

    def list_keys(self) -> list[str]:
        """Every key in the bucket — the GC reconciliation's inventory."""
        keys: list[str] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=S3_BUCKET, Key=key)


# Module-level singleton; tests swap it for an in-memory fake. Constructing a
# boto3 client opens no connection, so this is import-safe.
store = Storage()
