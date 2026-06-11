"""
Unified LLM client routing to local Qwen3 via Ollama.
Ollama runs an OpenAI-compatible API at localhost:11434.
Uses qwen3:14b for all tasks (classification + tailoring).
"""

import asyncio
import json
import logging
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


async def complete(
    system: str,
    user: str,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> LLMResponse:
    """
    Call Qwen3 via Ollama. Returns the response text.
    Appends /no_think to system prompt to skip thinking tokens in structured tasks.
    """
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
            async with httpx.AsyncClient(base_url=OLLAMA_BASE, timeout=300.0) as client:
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


async def complete_json(system: str, user: str, max_tokens: int = 1024) -> dict:
    """Call LLM and parse JSON response. Raises ValueError on bad JSON."""
    response = await complete(system, user, json_mode=True, max_tokens=max_tokens)
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        # Try to extract JSON block if model wrapped it
        import re
        match = re.search(r'\{.*\}', response.content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"LLM returned non-JSON: {response.content[:300]}")
