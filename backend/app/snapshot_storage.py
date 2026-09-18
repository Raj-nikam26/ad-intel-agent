"""
snapshot_storage.py
-------------------
Where each version's full dataframe is kept: local disk by default, or
S3-compatible object storage (MinIO locally, S3/R2 in production).

Format is gzip pickle, not Parquet - see data_store.py for why.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from app.config import settings


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
        df.to_pickle(tmp, compression="gzip")
        tmp.replace(path)  # never leave a half-written version behind

    def read(self, session_id: str, version: int) -> pd.DataFrame | None:
        path = self._path(session_id, version)
        return pd.read_pickle(path, compression="gzip") if path.exists() else None


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
        buf = io.BytesIO()
        df.to_pickle(buf, compression={"method": "gzip"})
        # A PUT either completes or does not exist, so no temp-file dance.
        self.client.put_object(Bucket=self.bucket, Key=self._key(session_id, version), Body=buf.getvalue())

    def read(self, session_id: str, version: int) -> pd.DataFrame | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(session_id, version))
        except self.client.exceptions.NoSuchKey:
            return None
        return pd.read_pickle(io.BytesIO(obj["Body"].read()), compression={"method": "gzip"})


def make_snapshot_storage(root: Path):
    return S3Snapshots() if settings.use_s3 else LocalSnapshots(root)
