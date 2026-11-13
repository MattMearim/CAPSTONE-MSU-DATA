from __future__ import annotations
import os
from pathlib import Path
from functools import lru_cache
import re
import yaml

class Config:
    def __init__(self, config_dir: str | Path | None = None, *, create_dirs: bool = True):
        project_dir = Path(__file__).resolve().parents[2]
        self.config_dir = Path(config_dir or os.getenv("FRIB_CONFIG_DIR", str(project_dir / "config"))).resolve()
        project_dir = self.config_dir.parent
        self.app = self._load("app.yaml")
        self.models = self._load("models.yaml")
        from frib_ds.ai_settings import saved_llm_config
        self.models.setdefault('llm', {}).update(saved_llm_config(self.config_dir))
        self.rag = self._load("rag.yaml")
        self.processing = self._load("processing.yaml")
        self.domains = self._load("domains.yaml")
        data_dir = Path(os.getenv("FRIB_DATA_DIR", self.app.get("app", {}).get("data_dir", "data-local-ai")))
        if not data_dir.is_absolute():
            data_dir = project_dir / data_dir
        self.data_dir = data_dir
        self.database_path = data_dir / "frib.db"
        self.event_dir = data_dir / "events"
        self.chroma_dir = data_dir / "chroma"
        self.document_dir = data_dir / "documents"
        self.prompts_dir = Path(self.app.get("app", {}).get("prompts_dir", "prompts"))
        if not self.prompts_dir.is_absolute():
            self.prompts_dir = project_dir / self.prompts_dir
        if create_dirs:
            self.event_dir.mkdir(parents=True, exist_ok=True)
            self.chroma_dir.mkdir(parents=True, exist_ok=True)

        # Environment overrides are intentionally simple and explicit.
        self.models.setdefault("llm", {})
        self.models.setdefault("embeddings", {})
        self.models.setdefault("vector_store", {})
        self.models["llm"]["provider"] = os.getenv("FRIB_LLM_PROVIDER", self.models["llm"].get("provider", "ollama"))
        self.models["llm"]["model"] = os.getenv("FRIB_LLM_MODEL", self.models["llm"].get("model", "qwen3:8b"))
        self.models["embeddings"]["provider"] = os.getenv("FRIB_EMBEDDING_PROVIDER", self.models["embeddings"].get("provider", "sentence_transformers"))
        self.models["embeddings"]["model"] = os.getenv("FRIB_EMBEDDING_MODEL", self.models["embeddings"].get("model", "all-MiniLM-L6-v2"))
        if os.getenv("FRIB_EMBEDDING_CACHE"):
            self.models["embeddings"]["cache_folder"] = os.environ["FRIB_EMBEDDING_CACHE"]
        self.models["vector_store"]["provider"] = os.getenv("FRIB_VECTOR_PROVIDER", self.models["vector_store"].get("provider", "sqlite"))
        self.models["llm"]["ollama_base_url"] = os.getenv("OLLAMA_BASE_URL", self.models["llm"].get("ollama_base_url", "http://localhost:11434"))
        self.models["llm"]["lmstudio_base_url"] = os.getenv("LMSTUDIO_BASE_URL", self.models["llm"].get("lmstudio_base_url", "http://localhost:1234/v1"))

    def _load(self, name: str) -> dict:
        path = self.config_dir / name
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def scenario(self, name: str) -> dict:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", name):
            raise ValueError("Scenario names must be plain identifiers without path components.")
        path = self.config_dir / "scenarios" / f"{name}.yaml"
        if path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(self.config_dir):
            raise ValueError("Scenario configuration must stay inside the configuration folder.")
        if not path.exists():
            raise FileNotFoundError(f"Scenario config not found: {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
