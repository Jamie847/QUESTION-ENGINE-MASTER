"""Voyage embeddings. Tests inject a fake; production calls the standalone API."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from swarm.settings import get_settings

log = logging.getLogger("swarm.memory")

EmbedFn = Callable[..., list[list[float]]]

_override: EmbedFn | None = None

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
BATCH = 128


def use_embedder(fn: EmbedFn | None) -> None:
    """Test hook. Pass None to restore the live client."""
    global _override
    _override = fn


def embed_texts(
    texts: Sequence[str],
    *,
    input_type: str = "document",
    model: str | None = None,
    dims: int | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    if _override is not None:
        return _override(list(texts), input_type=input_type)
    settings = get_settings()
    key = (settings.voyage_api_key or "").strip()
    if not key:
        raise RuntimeError("VOYAGE_API_KEY is empty")
    model = model or settings.embed_model
    dims = dims or settings.embed_dims
    out: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        chunk = list(texts[start : start + BATCH])
        out.extend(
            _voyage_call(chunk, key=key, model=model, dims=dims, input_type=input_type)
        )
    return out


def _voyage_call(
    texts: list[str],
    *,
    key: str,
    model: str,
    dims: int,
    input_type: str,
) -> list[list[float]]:
    body: dict[str, Any] = {
        "input": texts,
        "model": model,
        "input_type": input_type,
        "output_dimension": dims,
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            VOYAGE_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
    rows = sorted(payload.get("data") or [], key=lambda row: int(row["index"]))
    if len(rows) != len(texts):
        raise RuntimeError(f"voyage returned {len(rows)} vectors for {len(texts)} texts")
    return [list(row["embedding"]) for row in rows]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
