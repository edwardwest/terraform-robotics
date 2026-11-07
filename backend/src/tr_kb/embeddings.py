"""Text embeddings for knowledge search.

- `vertex`: Google's text-embedding-005 on Vertex AI (768 dimensions), used in the cloud.
- `hash`: a deterministic bag-of-words hash, for tests and local development without credentials.
- `none`: no embeddings; search falls back to keywords only.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from functools import lru_cache

DIM = 768
VERTEX_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-005")
BATCH = 16


class HashEmbedder:
    name = "hash"

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z0-9]+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % DIM] += 1.0 if (h >> 9) & 1 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class VertexEmbedder:
    name = "vertex"

    def __init__(self, project: str, region: str):
        self.project, self.region = project, region

    def _token(self) -> str:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        import httpx

        task = "RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY"
        url = (f"https://{self.region}-aiplatform.googleapis.com/v1/projects/{self.project}/locations/{self.region}"
               f"/publishers/google/models/{VERTEX_MODEL}:predict")
        token = self._token()
        out: list[list[float]] = []
        with httpx.Client(timeout=60) as client:
            for i in range(0, len(texts), BATCH):
                body = {"instances": [{"content": t[:8000], "task_type": task} for t in texts[i : i + BATCH]],
                        "parameters": {"outputDimensionality": DIM}}
                r = client.post(url, json=body, headers={"Authorization": f"Bearer {token}"})
                r.raise_for_status()
                out.extend(p["embeddings"]["values"] for p in r.json()["predictions"])
        return out


@lru_cache
def get_embedder():
    mode = os.environ.get("EMBEDDINGS", "vertex" if os.environ.get("GCP_PROJECT") else "hash")
    if mode == "none":
        return None
    if mode == "vertex":
        return VertexEmbedder(os.environ["GCP_PROJECT"], os.environ.get("VERTEX_EMBED_REGION", os.environ.get("GCP_REGION", "us-west1")))
    return HashEmbedder()


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
