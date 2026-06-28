"""S3-compatible storage adapter.

Targets any S3-compatible object store (AWS S3, Cloudflare R2, Backblaze B2 -
the provider is chosen for egress cost behind this single interface, per the
Database Strategy). ``boto3`` is imported lazily inside methods so the
dependency is only loaded when this backend is actually selected, keeping the
default (local) startup light.

The synchronous ``boto3`` calls are dispatched to a thread to avoid blocking the
event loop. (A fully-async client is a later optimisation behind this same
contract.)

This adapter is structurally complete; it is exercised only when
``OLYMPUS_STORAGE__BACKEND=s3`` and valid credentials are configured.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from olympus.domain.contracts.storage import StorageObject, StoragePort
from olympus.platform.errors import ConfigurationError, StorageError
from olympus.platform.logging import get_logger

if TYPE_CHECKING:
    from olympus.platform.config.settings import StorageSettings

log = get_logger(__name__)


class S3Storage(StoragePort):
    """Store objects in an S3-compatible bucket."""

    def __init__(self, settings: StorageSettings) -> None:
        if not settings.s3_bucket:
            raise ConfigurationError("S3 storage selected but no bucket configured.")
        self._bucket = settings.s3_bucket
        self._settings = settings
        self._client: Any | None = None
        log.info("s3_storage_init", bucket=self._bucket, region=settings.s3_region)

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # lazy import: only when the S3 backend is used.

            self._client = boto3.client(
                "s3",
                region_name=self._settings.s3_region,
                endpoint_url=self._settings.s3_endpoint_url,
                aws_access_key_id=self._settings.s3_access_key_id,
                aws_secret_access_key=self._settings.s3_secret_access_key,
            )
        return self._client

    async def put(
        self, key: str, data: bytes, *, content_type: str | None = None
    ) -> StorageObject:
        def _put() -> None:
            extra = {"ContentType": content_type} if content_type else {}
            self._get_client().put_object(Bucket=self._bucket, Key=key, Body=data, **extra)

        try:
            await asyncio.to_thread(_put)
        except Exception as exc:
            raise StorageError("Failed to write object to S3.", details={"key": key}) from exc
        return StorageObject(key=key, size_bytes=len(data), content_type=content_type)

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str | None = None,
    ) -> StorageObject:
        import os
        import tempfile

        # Buffer the stream to a temp file on disk (bounded memory), then upload
        # with boto3's multipart-capable upload_fileobj.
        fd, tmp_path = tempfile.mkstemp(prefix="olympus-upload-")
        size = 0
        try:
            handle = os.fdopen(fd, "w+b")
            try:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    await asyncio.to_thread(handle.write, chunk)
                    size += len(chunk)
                await asyncio.to_thread(handle.flush)
                await asyncio.to_thread(handle.seek, 0)

                def _upload() -> None:
                    extra = {"ContentType": content_type} if content_type else {}
                    self._get_client().upload_fileobj(handle, self._bucket, key, ExtraArgs=extra)

                await asyncio.to_thread(_upload)
            finally:
                await asyncio.to_thread(handle.close)
        except Exception as exc:
            raise StorageError("Failed to stream object to S3.", details={"key": key}) from exc
        finally:
            await asyncio.to_thread(
                lambda: os.unlink(tmp_path) if os.path.exists(tmp_path) else None
            )
        return StorageObject(key=key, size_bytes=size, content_type=content_type)

    async def get(self, key: str) -> bytes:
        def _get() -> bytes:
            response = self._get_client().get_object(Bucket=self._bucket, Key=key)
            body: bytes = response["Body"].read()
            return body

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            raise StorageError("Failed to read object from S3.", details={"key": key}) from exc

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._get_client().head_object(Bucket=self._bucket, Key=key)
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_head)

    async def delete(self, key: str) -> None:
        def _delete() -> None:
            self._get_client().delete_object(Bucket=self._bucket, Key=key)

        try:
            await asyncio.to_thread(_delete)
        except Exception as exc:
            raise StorageError("Failed to delete object from S3.", details={"key": key}) from exc

    async def list_keys(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            keys: list[str] = []
            paginator = self._get_client().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
            return keys

        try:
            return await asyncio.to_thread(_list)
        except Exception as exc:
            raise StorageError("Failed to list objects in S3.", details={"prefix": prefix}) from exc

    async def generate_access_url(self, key: str, *, expires_in: int = 3600) -> str:
        def _presign() -> str:
            url: str = self._get_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

        try:
            return await asyncio.to_thread(_presign)
        except Exception as exc:
            raise StorageError("Failed to presign URL.", details={"key": key}) from exc
