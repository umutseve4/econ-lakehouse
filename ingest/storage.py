"""Storage abstraction: the bronze lake on local disk OR an S3-compatible store.

The rest of the codebase never touches a filesystem API directly — it goes
through `Storage`, which fsspec resolves from a URI:

    warehouse/bronze      -> local filesystem (default, backwards compatible)
    s3://bucket/prefix    -> S3-compatible object store (AWS S3, MinIO, ...)
    memory://prefix       -> in-process memory filesystem (unit tests)

S3 credentials come from the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
environment variables. A non-AWS endpoint (e.g. a MinIO container) is set via
LAKE_S3_ENDPOINT, e.g. LAKE_S3_ENDPOINT=http://localhost:9000.
No credential is ever hardcoded here.
"""

from __future__ import annotations

import os
from pathlib import Path

import fsspec
import pandas as pd


class Storage:
    """Thin facade over an fsspec filesystem rooted at a base prefix."""

    def __init__(self, fs: fsspec.AbstractFileSystem, base: str, is_local: bool):
        self.fs = fs
        self.base = base.rstrip("/")
        self.is_local = is_local

    @classmethod
    def from_uri(cls, uri: str | Path) -> "Storage":
        uri = str(uri)
        if uri.startswith("s3://"):
            kwargs: dict = {}
            endpoint = os.environ.get("LAKE_S3_ENDPOINT")
            if endpoint:
                kwargs["client_kwargs"] = {"endpoint_url": endpoint}
            fs = fsspec.filesystem("s3", **kwargs)
            return cls(fs, uri[len("s3://"):], is_local=False)
        if uri.startswith("memory://"):
            return cls(fsspec.filesystem("memory"), uri[len("memory://"):], is_local=False)
        return cls(fsspec.filesystem("file"), str(Path(uri).absolute()), is_local=True)

    def join(self, *parts: str) -> str:
        return "/".join([self.base, *parts])

    def exists(self, path: str) -> bool:
        self.fs.invalidate_cache()
        return self.fs.exists(path)

    def glob(self, pattern: str) -> list[str]:
        """Glob relative to the base prefix; returns full backend paths."""
        self.fs.invalidate_cache()
        return sorted(self.fs.glob(self.join(pattern)))

    def read_parquet(self, path: str) -> pd.DataFrame:
        with self.fs.open(path, "rb") as f:
            return pd.read_parquet(f)

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        parent = path.rsplit("/", 1)[0]
        try:
            self.fs.makedirs(parent, exist_ok=True)
        except Exception:  # noqa: BLE001 — object stores have no real dirs
            pass
        with self.fs.open(path, "wb") as f:
            df.to_parquet(f, index=False)
