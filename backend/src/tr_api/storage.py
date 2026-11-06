"""File storage for uploads and generated rasters: a local folder in development, Cloud Storage on Google Cloud.

Paths are relative keys such as `projects/<id>/terrain/dem.tif`.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from .config import get_settings


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError("Storage key escapes the storage root")
        return p

    def save_stream(self, key: str, stream: BinaryIO) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "wb") as f:
            shutil.copyfileobj(stream, f)

    def save_file(self, key: str, local_path: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, p)

    def local_path(self, key: str) -> str:
        """A readable local path for the object (the file itself for local storage)."""
        return str(self._path(key))

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class GcsStorage:
    def __init__(self, bucket: str, prefix: str):
        from google.cloud import storage  # optional dependency: pip install .[gcp]

        self.bucket = storage.Client().bucket(bucket)
        self.prefix = prefix.strip("/")
        self.cache = Path(tempfile.gettempdir()) / "tr-gcs-cache"

    def _blob(self, key: str):
        name = f"{self.prefix}/{key}" if self.prefix else key
        return self.bucket.blob(name)

    def save_stream(self, key: str, stream: BinaryIO) -> None:
        self._blob(key).upload_from_file(stream, rewind=True)

    def save_file(self, key: str, local_path: str) -> None:
        self._blob(key).upload_from_filename(local_path)

    def local_path(self, key: str) -> str:
        dest = self.cache / key
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._blob(key).download_to_filename(str(dest))
        return str(dest)

    def exists(self, key: str) -> bool:
        return self._blob(key).exists()


@lru_cache
def get_storage():
    url = urlparse(get_settings().storage_url)
    if url.scheme == "gs":
        return GcsStorage(url.netloc, url.path)
    if url.scheme in ("file", ""):
        return LocalStorage(url.path or os.path.join(tempfile.gettempdir(), "terraform-data"))
    raise ValueError(f"Unsupported STORAGE_URL scheme: {url.scheme}")
