"""Text embeddings for hybrid SOP retrieval (FR-12.3).

- `GeminiEmbedder`: google-genai `embed_content` (default `gemini-embedding-001`, 768 dims).
  Embedding requests have their own free-tier quota, separate from generate requests.
- `HashEmbedder`: deterministic bag-of-words hashing, for tests and CI (no network, and
  similar wording gives similar vectors, so ranking tests are meaningful).

Vectors are L2-normalised so cosine distance (pgvector `<=>`) behaves the same for both.
"""

import hashlib
import math
import re
from typing import Any, Literal, Protocol

from app.db.models.document import EMBEDDING_DIMENSIONS

Task = Literal["document", "query"]
_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str], task: Task) -> list[list[float]]: ...


def normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def chunk_text(document_title: str, section_title: str, text: str) -> str:
    """What gets embedded for one SOP section."""
    return f"{document_title} - {section_title}\n{text}"


class HashEmbedder:
    model = "hash-bow-v1"

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls = 0

    def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        self.calls += 1
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in _WORD.findall(text.lower()):
                if len(word) < 3:
                    continue
                slot = int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dimensions
                vector[slot] += 1.0
            vectors.append(normalise(vector))
        return vectors


class GeminiEmbedder:
    def __init__(
        self,
        client: Any,
        model: str = "gemini-embedding-001",
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str], task: Task) -> list[list[float]]:
        from google.genai import types

        response = self.client.models.embed_content(
            model=self.model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY",
                output_dimensionality=self.dimensions,
            ),
        )
        return [normalise(list(e.values or [])) for e in response.embeddings or []]
