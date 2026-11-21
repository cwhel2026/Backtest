"""Modular LLM providers — JSON completions only, no code execution."""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 45.0


@dataclass(frozen=True)
class LlmUsage:
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


@dataclass(frozen=True)
class LlmJsonResult:
    data: dict[str, Any]
    usage: LlmUsage
    model: str
    provider_slug: str


class LlmProvider(ABC):
    slug: str
    display_name: str
    default_model: str
    docs_url: str

    @abstractmethod
    def api_key_configured(self) -> bool: ...

    @abstractmethod
    def complete_json(self, *, system: str, user: str, model: str | None = None) -> LlmJsonResult: ...

    def test_connection(self, model: str | None = None) -> tuple[bool, str]:
        try:
            r = self.complete_json(
                system="Return JSON only.",
                user='{"ping": true}',
                model=model,
            )
            return True, f"OK model={r.model}"
        except Exception as exc:
            return False, str(exc)[:300]


def _parse_json_content(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```", 2)[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)


class _OpenAICompat(LlmProvider):
    """OpenAI Chat Completions API shape."""

    slug = "openai"
    display_name = "OpenAI"
    default_model = "gpt-4o-mini"
    docs_url = "https://platform.openai.com/docs/api-reference/chat"

    def __init__(self, api_key: str) -> None:
        self._key = api_key.strip()

    def api_key_configured(self) -> bool:
        return bool(self._key)

    def complete_json(self, *, system: str, user: str, model: str | None = None) -> LlmJsonResult:
        model = model or self.default_model
        t0 = time.monotonic()
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.4,
                },
            )
            resp.raise_for_status()
            body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        lat = int((time.monotonic() - t0) * 1000)
        cost = (usage.get("prompt_tokens", 0) * 0.15 + usage.get("completion_tokens", 0) * 0.6) / 1_000_000
        return LlmJsonResult(
            data=_parse_json_content(content),
            usage=LlmUsage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), cost, lat),
            model=model,
            provider_slug=self.slug,
        )


class AnthropicProvider(LlmProvider):
    slug = "anthropic"
    display_name = "Anthropic"
    default_model = "claude-3-5-haiku-latest"
    docs_url = "https://docs.anthropic.com/en/api/messages"

    def __init__(self, api_key: str) -> None:
        self._key = api_key.strip()

    def api_key_configured(self) -> bool:
        return bool(self._key)

    def complete_json(self, *, system: str, user: str, model: str | None = None) -> LlmJsonResult:
        model = model or self.default_model
        t0 = time.monotonic()
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "system": system + "\nRespond with a single JSON object only.",
                    "messages": [{"role": "user", "content": user}],
                },
            )
            resp.raise_for_status()
            body = resp.json()
        blocks = body.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = body.get("usage") or {}
        lat = int((time.monotonic() - t0) * 1000)
        tin, tout = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        cost = (tin * 0.8 + tout * 4.0) / 1_000_000
        return LlmJsonResult(
            data=_parse_json_content(text),
            usage=LlmUsage(tin, tout, cost, lat),
            model=model,
            provider_slug=self.slug,
        )


class GeminiProvider(LlmProvider):
    slug = "google"
    display_name = "Google Gemini"
    default_model = "gemini-2.0-flash"
    docs_url = "https://ai.google.dev/gemini-api/docs"

    def __init__(self, api_key: str) -> None:
        self._key = api_key.strip()

    def api_key_configured(self) -> bool:
        return bool(self._key)

    def complete_json(self, *, system: str, user: str, model: str | None = None) -> LlmJsonResult:
        model = model or self.default_model
        t0 = time.monotonic()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self._key}"
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.post(
                url,
                json={
                    "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4},
                },
            )
            resp.raise_for_status()
            body = resp.json()
        parts = body["candidates"][0]["content"]["parts"]
        text = parts[0].get("text", "{}")
        meta = body.get("usageMetadata") or {}
        lat = int((time.monotonic() - t0) * 1000)
        tin = int(meta.get("promptTokenCount", 0))
        tout = int(meta.get("candidatesTokenCount", 0))
        return LlmJsonResult(
            data=_parse_json_content(text),
            usage=LlmUsage(tin, tout, (tin + tout) * 0.1 / 1_000_000, lat),
            model=model,
            provider_slug=self.slug,
        )


class _OpenAICompatEndpoint(LlmProvider):
    """DeepSeek, Moonshot, Grok, Qwen, Mistral — OpenAI-compatible chat."""

    def __init__(self, api_key: str, base_url: str, slug: str, display_name: str, default_model: str, docs_url: str) -> None:
        self._key = api_key.strip()
        self._base = base_url.rstrip("/")
        self.slug = slug
        self.display_name = display_name
        self.default_model = default_model
        self.docs_url = docs_url

    def api_key_configured(self) -> bool:
        return bool(self._key)

    def complete_json(self, *, system: str, user: str, model: str | None = None) -> LlmJsonResult:
        model = model or self.default_model
        t0 = time.monotonic()
        with httpx.Client(timeout=DEFAULT_TIMEOUT_S) as client:
            resp = client.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            body = resp.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage") or {}
        lat = int((time.monotonic() - t0) * 1000)
        return LlmJsonResult(
            data=_parse_json_content(content),
            usage=LlmUsage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), 0.0, lat),
            model=model,
            provider_slug=self.slug,
        )


PROVIDER_DEFS: list[dict[str, str]] = [
    {"slug": "openai", "env": "OPENAI_API_KEY", "class": "openai"},
    {"slug": "anthropic", "env": "ANTHROPIC_API_KEY", "class": "anthropic"},
    {"slug": "google", "env": "GOOGLE_AI_API_KEY", "class": "gemini"},
    {"slug": "moonshot", "env": "MOONSHOT_API_KEY", "class": "compat", "base": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "name": "Moonshot Kimi", "docs": "https://platform.moonshot.cn/docs"},
    {"slug": "deepseek", "env": "DEEPSEEK_API_KEY", "class": "compat", "base": "https://api.deepseek.com", "model": "deepseek-chat", "name": "DeepSeek", "docs": "https://api-docs.deepseek.com"},
    {"slug": "xai", "env": "XAI_API_KEY", "class": "compat", "base": "https://api.x.ai/v1", "model": "grok-2-latest", "name": "xAI Grok", "docs": "https://docs.x.ai/docs"},
    {"slug": "qwen", "env": "DASHSCOPE_API_KEY", "class": "compat", "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "name": "Alibaba Qwen", "docs": "https://www.alibabacloud.com/help/en/model-studio"},
    {"slug": "mistral", "env": "MISTRAL_API_KEY", "class": "compat", "base": "https://api.mistral.ai/v1", "model": "mistral-small-latest", "name": "Mistral AI", "docs": "https://docs.mistral.ai/api/"},
]


def _key_for_env(env_name: str) -> str:
    import os

    s = get_settings()
    mapping = {
        "OPENAI_API_KEY": s.openai_api_key,
        "ANTHROPIC_API_KEY": getattr(s, "anthropic_api_key", ""),
        "GOOGLE_AI_API_KEY": getattr(s, "google_ai_api_key", ""),
        "MOONSHOT_API_KEY": getattr(s, "moonshot_api_key", ""),
        "DEEPSEEK_API_KEY": getattr(s, "deepseek_api_key", ""),
        "XAI_API_KEY": getattr(s, "xai_api_key", ""),
        "DASHSCOPE_API_KEY": getattr(s, "dashscope_api_key", ""),
        "MISTRAL_API_KEY": getattr(s, "mistral_api_key", ""),
    }
    return (mapping.get(env_name) or os.getenv(env_name) or "").strip()


def build_provider(slug: str) -> LlmProvider | None:
    for d in PROVIDER_DEFS:
        if d["slug"] != slug:
            continue
        key = _key_for_env(d["env"])
        if d["class"] == "openai":
            return _OpenAICompat(key)
        if d["class"] == "anthropic":
            return AnthropicProvider(key)
        if d["class"] == "gemini":
            return GeminiProvider(key)
        return _OpenAICompatEndpoint(
            key, d["base"], d["slug"], d["name"], d["model"], d["docs"]
        )
    return None


def list_provider_catalog() -> list[dict[str, Any]]:
    out = []
    for d in PROVIDER_DEFS:
        key = _key_for_env(d["env"])
        out.append(
            {
                "slug": d["slug"],
                "display_name": d.get("name") or d["slug"].title(),
                "env_var": d["env"],
                "default_model": d.get("model") or "gpt-4o-mini",
                "docs_url": d.get("docs", ""),
                "key_configured": bool(key),
            }
        )
    return out


def get_provider(slug: str) -> LlmProvider:
    p = build_provider(slug)
    if not p:
        raise ValueError(f"Unknown AI provider slug: {slug}")
    return p