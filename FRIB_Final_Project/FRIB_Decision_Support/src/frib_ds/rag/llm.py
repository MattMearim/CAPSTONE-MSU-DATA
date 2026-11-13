from __future__ import annotations

from abc import ABC, abstractmethod
import json
import requests
from frib_ds.model_runtime import serialized_inference


def model_identity(provider):
    identity = getattr(provider, 'identity', None)
    return dict(identity) if isinstance(identity, dict) else {'provider': type(provider).__name__, 'model': getattr(provider, 'model', None)}


class LLMProvider(ABC):
    @property
    def identity(self):
        return {"provider": getattr(self, "provider_name", type(self).__name__), "model": getattr(self, "model", None)}

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        json_schema: dict | None = None
    ) -> str:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    def chat(self, messages, json_schema=None):
        if json_schema:
            return json.dumps({})

        return "Mock provider active. No production model was called."


class OllamaProvider(LLMProvider):
    provider_name = 'ollama'
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 300,
        context_length: int = 4096,
        max_output_tokens: int = 500,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens

    @serialized_inference
    def chat(self, messages, json_schema=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_length,
                "num_predict": self.max_output_tokens
            }
        }

        if json_schema:
            payload["format"] = json_schema

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
                proxies={"http": "", "https": ""},
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        if not response.ok or 300 <= getattr(response, 'status_code', 200) < 400:
            raise RuntimeError(
                f"Ollama returned HTTP {response.status_code}: "
                f"{response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Ollama returned a response that was not valid JSON: "
                f"{response.text}"
            ) from exc

        if "message" not in data or "content" not in data["message"]:
            raise RuntimeError(
                f"Ollama returned an unexpected response: {data}"
            )

        return data["message"]["content"]


class LMStudioProvider(LLMProvider):
    provider_name = 'lmstudio'
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 300,
        max_output_tokens: int = 500,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens

    @serialized_inference
    def chat(self, messages, json_schema=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
            "stream": False
        }

        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "frib_output",
                    "schema": json_schema,
                    "strict": True
                }
            }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
            allow_redirects=False,
            proxies={"http": "", "https": ""},
        )

        response.raise_for_status()
        if 300 <= getattr(response, 'status_code', 200) < 400:
            raise RuntimeError('Model server redirects are not allowed.')

        return response.json()["choices"][0]["message"]["content"]


def build_llm_provider(config: dict) -> LLMProvider:
    provider = config.get("provider", "ollama")
    model = config.get("model", "qwen3:8b")
    temperature = float(config.get("temperature", 0))
    timeout = int(config.get("timeout_seconds", 300))

    if provider == "mock":
        return MockLLMProvider()

    if provider == "ollama":
        return OllamaProvider(
            config.get(
                "ollama_base_url",
                "http://localhost:11434"
            ),
            model,
            temperature,
            timeout,
            context_length=int(config.get('context_length', 4096)),
            max_output_tokens=int(config.get('max_output_tokens', 500)),
        )

    if provider == "lmstudio":
        return LMStudioProvider(
            config.get(
                "lmstudio_base_url",
                "http://localhost:1234/v1"
            ),
            model,
            temperature,
            timeout,
            max_output_tokens=int(config.get('max_output_tokens', 500)),
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
