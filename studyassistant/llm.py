"""Local model access through Ollama's HTTP API (no cloud calls).

``LanguageModel`` is the small interface the app needs; ``OllamaModel``
implements it. Tests use a fake implementation instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Literal, Protocol

import httpx
import numpy as np

EmbedKind = Literal["document", "query"]

# Keep the models in memory between questions (Ollama unloads it after
# 5 idle minutes by default, and reloading takes ~20 s on a CPU).
KEEP_ALIVE = "2h"


class ModelUnavailable(RuntimeError):
    """Ollama is not running, or a model has not been pulled."""


class LanguageModel(Protocol):
    def embed(self, texts: list[str], kind: EmbedKind) -> np.ndarray: ...

    def chat_stream(self, messages: list[dict]) -> Iterator[str]: ...

    def chat_json(self, messages: list[dict], schema: dict, max_tokens: int | None = None) -> dict: ...


class OllamaModel:
    def __init__(
        self,
        base_url: str,
        chat_model: str,
        embed_model: str,
        timeout: float = 600.0,
        num_ctx: int = 8192,
        num_gpu: int | None = 0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.embed_model = embed_model
        # Ollama's default context is too small for a unit's worth of text.
        self.num_ctx = num_ctx
        # 0 = run on the CPU, like a lab PC without a GPU. None = let Ollama decide.
        self.num_gpu = num_gpu
        self.max_json_tokens = 3000
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------ status

    def status(self) -> dict:
        """Whether Ollama answers and which of our models are installed."""
        try:
            tags = self._client.get("/api/tags", timeout=5).json()
        except httpx.HTTPError as exc:
            return {"running": False, "error": str(exc)}
        installed = {m["name"] for m in tags.get("models", [])}

        def has(name: str) -> bool:
            return name in installed or f"{name}:latest" in installed

        return {
            "running": True,
            "chat_model": self.chat_model,
            "chat_model_installed": has(self.chat_model),
            "embed_model": self.embed_model,
            "embed_model_installed": has(self.embed_model),
        }

    def warm_up(self) -> None:
        """Load the chat model now, so the first student doesn't wait for it."""
        try:
            self._client.post(
                "/api/generate",
                json={"model": self.chat_model, "keep_alive": KEEP_ALIVE, "options": self._options(0)},
            )
            self.embed(["warm up"], kind="query")
        except (httpx.HTTPError, ModelUnavailable, RuntimeError):
            pass  # reported by /api/health instead

    # --------------------------------------------------------------- embedding

    def embed(self, texts: list[str], kind: EmbedKind) -> np.ndarray:
        # nomic-embed-text is trained with these task prefixes.
        prefix = "search_query: " if kind == "query" else "search_document: "
        if "nomic" not in self.embed_model:
            prefix = ""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 32):
            batch = [prefix + t for t in texts[start : start + 32]]
            # keep_alive: reloading the embedding model costs every first question 3 s.
            data = self._post("/api/embed", {"model": self.embed_model, "input": batch, "keep_alive": KEEP_ALIVE})
            vectors.extend(data["embeddings"])
        return np.asarray(vectors, dtype=np.float32)

    # -------------------------------------------------------------------- chat

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        payload = {
            "model": self.chat_model,
            "messages": messages,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "options": self._options(0.2),
        }
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as response:
                self._raise_for_status(response, read=True)
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    if "error" in event:
                        raise ModelUnavailable(event["error"])
                    token = event.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if event.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise ModelUnavailable(f"Ollama is not running at {self.base_url}") from exc

    def chat_json(self, messages: list[dict], schema: dict, max_tokens: int | None = None) -> dict:
        """Chat with output constrained to ``schema`` (Ollama structured outputs)."""
        data = self._post(
            "/api/chat",
            {
                "model": self.chat_model,
                "messages": messages,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "format": schema,
                # Cap the output: under a JSON schema a small model can loop
                # inside a string forever (seen: 10 minutes, then a timeout).
                "options": {**self._options(0.3), "num_predict": max_tokens or self.max_json_tokens},
            },
        )
        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model did not return valid JSON: {content[:200]}") from exc

    # ----------------------------------------------------------------- helpers

    def _options(self, temperature: float) -> dict:
        options = {"temperature": temperature, "num_ctx": self.num_ctx}
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        return options

    def _post(self, path: str, payload: dict) -> dict:
        try:
            response = self._client.post(path, json=payload)
        except httpx.ConnectError as exc:
            raise ModelUnavailable(f"Ollama is not running at {self.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise ModelUnavailable("The AI model took too long to answer. Please try again.") from exc
        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response, read: bool = False) -> None:
        if response.status_code < 400:
            return
        if read:
            response.read()
        try:
            message = response.json().get("error", response.text)
        except ValueError:
            message = response.text
        if response.status_code == 404 or "not found" in message.lower():
            raise ModelUnavailable(f"{message} (run: ollama pull <model>)")
        raise RuntimeError(f"Ollama error {response.status_code}: {message}")
