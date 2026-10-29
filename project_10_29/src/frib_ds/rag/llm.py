from __future__ import annotations

from abc import ABC, abstractmethod
import json
import requests


class LLMProvider(ABC):
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
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 300
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages, json_schema=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_gpu": 0,
                "num_ctx": 4096,
                "num_predict": 500
            }
        }

        if json_schema:
            payload["format"] = json_schema

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.base_url}: {exc}"
            ) from exc

        if not response.ok:
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
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 300
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages, json_schema=None):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
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
            timeout=self.timeout
        )

        response.raise_for_status()

        return response.json()["choices"][0]["message"]["content"]


def build_llm_provider(config: dict) -> LLMProvider:
    provider = config.get("provider", "mock")
    model = config.get("model", "")
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
            timeout
        )

    if provider == "lmstudio":
        return LMStudioProvider(
            config.get(
                "lmstudio_base_url",
                "http://localhost:1234/v1"
            ),
            model,
            temperature,
            timeout
        )

    raise ValueError(f"Unknown LLM provider: {provider}")