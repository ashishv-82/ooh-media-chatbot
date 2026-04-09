"""OpenAI text-embedding-3-small wrapper.

This is the ONLY module in the project allowed to import openai.
"""

from __future__ import annotations

import os
from typing import Iterable

from openai import OpenAI

MODEL = "text-embedding-3-small"
DIM = 1536
BATCH_SIZE = 100

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = OpenAI(api_key=api_key)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings with text-embedding-3-small.

    Batches in groups of BATCH_SIZE to stay well under any per-request limits.
    Returns vectors in the same order as the input.
    """
    if not texts:
        return []
    client = _get_client()
    out: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start : start + BATCH_SIZE]
        resp = client.embeddings.create(model=MODEL, input=batch)
        out.extend(item.embedding for item in resp.data)
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
