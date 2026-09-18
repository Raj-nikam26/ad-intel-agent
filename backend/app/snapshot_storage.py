"""
snapshot_storage.py
-------------------
Where each version's full dataframe is kept: local disk by default, or
S3-compatible object storage (MinIO locally, S3/R2 in production).

Format is gzip pickle, not Parquet - see data_store.py for why.

Unpickling can run code, so a snapshot planted in the bucket by someone
holding the storage keys would run on the server. With
SNAPSHOT_SIGNING_KEY set, each snapshot is prefixed with an HMAC-SHA256
of its bytes, and a snapshot whose signature does not match is refused
before it is unpickled. Snapshots written before a key was set carry no
signature and are still read, so turning signing on needs no migration.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import pickle
from pathlib import Path

import pandas as pd

from app.config import settings


_MAGIC = b"ADSIG1"
_SIG_LEN = 32


class SnapshotIntegrityError(RuntimeError):
    pass


def _signature(body: bytes) -> bytes:
    return hmac.new(settings.snapshot_signing_key.encode(), body, hashlib.sha256).digest()


def encode(df: pd.DataFrame) -> bytes:
    body = gzip.compress(pickle.dumps(df, protocol=pickle.HIGHEST_PROTOCOL), compresslevel=6)
    if settings.snapshot_signing_key:
        return _MAGIC + _signature(body) + body
    return body


def decode(data: bytes) -> pd.DataFrame:
    if data.startswith(_MAGIC):
        sig, body = data[len(_MAGIC):len(_MAGIC) + _SIG_LEN], data[len(_MAGIC) + _SIG_LEN:]
        if not settings.snapshot_signing_key:
            raise SnapshotIntegrityError("Snapshot is signed but SNAPSHOT_SIGNING_KEY is not set.")
        if not hmac.compare_digest(sig, _signature(body)):
            raise SnapshotIntegrityError("Snapshot signature does not match; refusing to load it.")
    else:
        body = data
    return pickle.loads(gzip.decompress(body))  # noqa: S301 - signature checked above when enabled


class LocalSnapshots:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str, version: int) -> Path:
        return self.root / session_id / f"v{version}.pkl.gz"

    def write(self, session_id: str, version: int, df: pd.DataFrame) -> None:
        path = self._path(session_id, version)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(encode(df))
        tmp.replace(path)  # never leave a half-written version behind

    def read(self, session_id: str, version: int) -> pd.DataFrame | None:
        path = self._path(session_id, version)
        return decode(path.read_bytes()) if path.exists() else None


class S3Snapshots:
    def __init__(self):
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        # Create the bucket if it is missing. Providers that restrict bucket
        # creation (or listing) through the S3 API expect it to be made in
        # their dashboard first, so a refusal here is not fatal.
        try:
            existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
            if self.bucket not in existing:
                self.client.create_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _key(session_id: str, version: int) -> str:
        return f"{session_id}/v{version}.pkl.gz"

    def write(self, session_id: str, version: int, df: pd.DataFrame) -> None:
        # A PUT either completes or does not exist, so no temp-file dance.
        self.client.put_object(Bucket=self.bucket, Key=self._key(session_id, version), Body=encode(df))

    def read(self, session_id: str, version: int) -> pd.DataFrame | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(session_id, version))
        except self.client.exceptions.NoSuchKey:
            return None
        return decode(obj["Body"].read())


def make_snapshot_storage(root: Path):
    return S3Snapshots() if settings.use_s3 else LocalSnapshots(root)
