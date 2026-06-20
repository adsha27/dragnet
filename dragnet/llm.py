"""
Unified LLM client.
Default: local Qwen3 via Ollama (cost-free, CPU-bound, slow for large batches).
Fallback: Anthropic API when ANTHROPIC_API_KEY is set and ollama is unreachable
          OR when USE_ANTHROPIC=1 env var is set for fast one-off batch tasks.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass

import httpx

from dragnet.config import settings

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434/v1"

# Ollama on CPU can only run one inference at a time — serialize all calls.
_ollama_sem = asyncio.Semaphore(1)


@dataclass
class LLMResponse:
    content: str
    model: str


def _use_anthropic() -> bool:
    return os.environ.get("USE_ANTHROPIC", "").lower() in ("1", "true", "yes")


async def complete(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> LLMResponse:
    if _use_anthropic() and settings.anthropic_api_key:
        return await _complete_anthropic(system, user, json_mode, max_tokens)
    return await _complete_ollama(system, user, json_mode, max_tokens)


async def _complete_ollama(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> LLMResponse:
    model = settings.ollama_model
    messages = [
        {"role": "system", "content": system + ("\n/no_think" if json_mode else "")},
        {"role": "user", "content": user},
    ]
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.3 if json_mode else 0.7,
        },
    }
    if json_mode:
        payload["format"] = "json"

    async with _ollama_sem:
        try:
            async with httpx.AsyncClient(base_url=OLLAMA_BASE, timeout=600.0) as client:
                resp = await client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return LLMResponse(content=text.strip(), model=model)
        except httpx.ConnectError:
            raise RuntimeError(
                "Ollama not running. Start with: ollama serve\n"
                f"Then pull model: ollama pull {model}"
            )
        except Exception as e:
            logger.error(f"LLM call failed: {type(e).__name__}: {e}")
            raise


async def _complete_anthropic(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> LLMResponse:
    model = settings.classification_model  # claude-haiku-4-5
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if json_mode:
        # Haiku respects JSON instruction in system prompt — no special param needed
        pass

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["content"][0]["text"]
        return LLMResponse(content=text.strip(), model=model)


async def complete_json(system: str, user: str, max_tokens: int = 1024) -> dict | list:
    """Call LLM and parse JSON response (object or array). Raises ValueError on bad JSON."""
    response = await complete(system, user, json_mode=True, max_tokens=max_tokens)
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        import re
        match = re.search(r'(\[.*\]|\{.*\})', response.content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"LLM returned non-JSON: {response.content[:300]}")
