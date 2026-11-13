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
        device: str = "cpu",
        cache_folder: str | None = None,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise RuntimeError(
                "Could not import SentenceTransformers and its required dependencies. "
                "Run the Start FRIB launcher to repair the application environment."
            ) from exc

        self.model_name = model_name
        self.device = device

        # Keep embeddings on CPU so Ollama/Qwen can use the GPU.
        try:
            options = {"device": device}
            if cache_folder:
                options["cache_folder"] = cache_folder
            self.model = SentenceTransformer(model_name, **options)
        except Exception as exc:
            raise RuntimeError(
                f"Could not load semantic embedding model {model_name!r}. "
                "The first model download needs internet access; check the model cache "
                "and run the AI setup again. Hash embeddings were not substituted."
            ) from exc

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

    provider = config.get("provider", "sentence_transformers")

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
            ),
            cache_folder=config.get("cache_folder"),
        )

    raise ValueError(
        f"Unknown embedding provider: {provider}"
    )
