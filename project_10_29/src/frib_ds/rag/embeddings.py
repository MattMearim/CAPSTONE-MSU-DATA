from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import re
import numpy as np


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic lightweight fallback for tests/demo.
    Not recommended for final retrieval quality.
    """

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = []

        for text in texts:
            vector = np.zeros(self.dimensions, dtype=float)

            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode()).hexdigest()
                value = int(digest[:16], 16)

                index = value % self.dimensions
                sign = 1 if (value >> 4) % 2 else -1

                vector[index] += sign

            norm = np.linalg.norm(vector)

            if norm:
                vector = vector / norm

            result.append(vector.tolist())

        return result


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str,
        device: str = "cpu"
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install the 'rag' extra to use SentenceTransformers"
            ) from exc

        self.model_name = model_name
        self.device = device

        # Keep embeddings on CPU so Ollama/Qwen can use the GPU.
        self.model = SentenceTransformer(
            model_name,
            device=device
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False
        )

        return vectors.tolist()


def build_embedding_provider(
    config: dict
) -> EmbeddingProvider:

    provider = config.get("provider", "hash")

    if provider == "hash":
        return HashEmbeddingProvider(
            int(config.get("dimensions", 384))
        )

    if provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(
            model_name=config.get(
                "model",
                "all-MiniLM-L6-v2"
            ),
            device=config.get(
                "device",
                "cpu"
            )
        )

    raise ValueError(
        f"Unknown embedding provider: {provider}"
    )
