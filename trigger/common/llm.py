"""The LangChain model factory both agents share.

The model is Sarvam, reached through its OpenAI-compatible endpoint -- the
same BASE_URL and MODEL the existing `signaldesk.model` layer uses, imported
rather than restated, so a model change there carries here.
"""
from __future__ import annotations

import json
import os
import re

from . import config as _cfg          # noqa: F401  -- puts service/ on sys.path


def api_key() -> str:
    return os.environ.get("SARVAM_API_KEY", "").strip()


def build_llm(cfg, llm=None):
    """The chat model, or None when there is no key to call with.

    `llm` injects a model instead of constructing the Sarvam one -- the same
    `model=None` seam `signaldesk.compose` uses, so a chain can be exercised
    without a network call.
    """
    if llm is not None:
        return llm
    if not api_key():
        return None
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=cfg.model,
        base_url=cfg.base_url,
        api_key=api_key(),
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=120,
        max_retries=1,
    )


def message_text(message) -> str:
    """A chat message's text, whichever shape the provider returned."""
    text = message.content if hasattr(message, "content") else str(message)
    if isinstance(text, list):          # some providers return content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return text


def lenient_json(text: str) -> dict | None:
    """Sarvam sometimes wraps JSON in a fence or trails a sentence after it.
    Take the outermost JSON object and try that before giving up."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError:
            continue
    return None
