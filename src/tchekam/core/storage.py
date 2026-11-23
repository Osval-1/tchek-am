import uuid
from typing import Protocol

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings


class ObjectNotFoundError(KeyError):
    pass


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def signed_url(self, key: str, ttl_seconds: int) -> str: ...
    def delete(self, key: str) -> None: ...


def new_key(prefix: str = "evidence") -> str:
    # Keys are never derived from user input (path traversal, enumeration, PII in keys).
    return f"{prefix}/{uuid.uuid4().hex}"


class InMemoryObjectStore:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._objects[key] = (data, content_type)
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._objects[key][0]
        except KeyError:
            raise ObjectNotFoundError(key) from None

    def signed_url(self, key: str, ttl_seconds: int) -> str:
        return f"memory://{key}?ttl={ttl_seconds}"

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class S3ObjectStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
        sse: bool = False,
    ) -> None:
        self.bucket = bucket
        self.sse = sse
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            # Path style works for SeaweedFS/MinIO; SigV4 is required for presigned URLs on R2.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    @classmethod
    def from_settings(cls) -> "S3ObjectStore":
        return cls(
            endpoint_url=settings.S3_ENDPOINT_URL,
            bucket=settings.S3_BUCKET,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            region=settings.S3_REGION,
            sse=settings.S3_SSE,
        )

    def put(self, key: str, data: bytes, content_type: str) -> str:
        extra = {"ServerSideEncryption": "AES256"} if self.sse else {}
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra
        )
        return key

    def get(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                raise ObjectNotFoundError(key) from exc
            raise

    def signed_url(self, key: str, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


def get_object_store() -> ObjectStore:
    backend = settings.OBJECT_STORE_BACKEND
    if backend == "memory":
        return InMemoryObjectStore()
    if backend == "s3":
        return S3ObjectStore.from_settings()
    raise ValueError(f"Unknown OBJECT_STORE_BACKEND: {backend!r}")
