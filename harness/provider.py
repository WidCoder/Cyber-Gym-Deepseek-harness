"""Environment-only provider configuration shared by the adapters."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    api_key: str
    api_key_env: str
    base_url: str
    api_format: str


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return ""


def resolve_llm_config() -> LLMConfig:
    raw = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    aliases = {
        "deepseek": "deepseek",
        "deepseek-official": "deepseek",
        "openai": "openai",
        "openai-compatible": "openai",
        "openai_chat": "openai",
        "glm": "openai",
        "gpt": "openai",
        "anthropic": "anthropic",
        "claude": "anthropic",
    }
    provider = aliases.get(raw)
    if provider is None:
        raise RuntimeError(
            f"unsupported LLM_PROVIDER={raw}; use deepseek, openai-compatible, glm, gpt, or anthropic"
        )

    deepseek_anthropic = (
        raw in {"deepseek", "deepseek-official"}
        and os.getenv("DEEPSEEK_API_MODE", "native").lower() == "anthropic"
    )
    if deepseek_anthropic:
        provider = "anthropic"

    default_key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }[provider]
    if raw == "glm":
        default_key_env = "GLM_API_KEY"
    api_key_env = os.getenv("LLM_API_KEY_ENV", "")
    if not api_key_env:
        api_key_env = default_key_env
        if deepseek_anthropic and os.getenv("DEEPSEEK_API_KEY"):
            api_key_env = "DEEPSEEK_API_KEY"
        elif provider == "anthropic" and not os.getenv(api_key_env) and os.getenv("ANTHROPIC_AUTH_TOKEN"):
            api_key_env = "ANTHROPIC_AUTH_TOKEN"
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise RuntimeError("LLM_API_KEY_ENV must be a valid environment variable name")
    api_key = os.getenv(api_key_env, "")

    if provider == "deepseek":
        base_url = _first_env("LLM_BASE_URL", "DEEPSEEK_BASE_URL", "OPENCODE_BASE_URL") or "https://api.deepseek.com"
        default_format = "deepseek"
    elif provider == "anthropic":
        base_url = _first_env("LLM_BASE_URL", "ANTHROPIC_BASE_URL", "OPENCODE_BASE_URL")
        if not base_url:
            base_url = "https://api.deepseek.com/anthropic" if deepseek_anthropic else "https://api.anthropic.com"
        default_format = "anthropic-messages"
    else:
        base_url = _first_env("LLM_BASE_URL", "OPENAI_BASE_URL", "GLM_BASE_URL", "OPENCODE_BASE_URL") or "https://api.openai.com/v1"
        default_format = "openai-completions"

    api_format = (os.getenv("LLM_API_FORMAT") or default_format).lower()
    allowed = {
        "deepseek": {"deepseek"},
        "anthropic": {"anthropic-messages"},
        "openai": {"openai-completions", "openai-responses"},
    }[provider]
    if api_format not in allowed:
        raise RuntimeError(
            f"LLM_API_FORMAT={api_format} is incompatible with {provider}; use {', '.join(sorted(allowed))}"
        )
    if not api_key:
        raise RuntimeError(f"API key is required in environment variable {api_key_env}")
    return LLMConfig(provider, api_key, api_key_env, base_url, api_format)
