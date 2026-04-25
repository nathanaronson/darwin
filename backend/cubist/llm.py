"""Shared LLM client with provider dispatch (Claude or Gemini).

Every LLM call in Cubist goes through this module so we have one place
to tune concurrency, retries, and rate-limit handling. The provider is
selected by ``settings.llm_provider``:

    LLM_PROVIDER=claude   (default — uses ANTHROPIC_API_KEY)
    LLM_PROVIDER=gemini   (uses GOOGLE_API_KEY)

Callers (strategist, builder, baseline engine) do NOT branch on the
provider. `complete()` returns a list of content blocks with the same
shape regardless of backend:

    block.type in {"text", "tool_use"}
    block.text                           # when type == "text"
    block.name, block.input (dict)       # when type == "tool_use"

For Gemini we wrap response parts in ``SimpleNamespace`` so agent code
that iterates Anthropic ``ContentBlock`` objects keeps working without
change.
"""

from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Any

from cubist.config import settings

log = logging.getLogger("cubist.llm")

# Per-loop caches. The orchestrator's agents (strategist/builder) run on
# the main event loop, while engines run on private per-call loops in
# worker threads (see ``cubist.tournament.referee._run_select_move``).
# ``asyncio.Semaphore`` and the SDK clients hold loop-bound locks
# internally, so we keep one of each per running loop and let the
# referee call ``cleanup_loop()`` when its private loop is torn down.
_anthropic_clients: dict[int, Any] = {}
_gemini_clients: dict[int, Any] = {}
_sems: dict[int, asyncio.Semaphore] = {}


def _loop_key() -> int:
    return id(asyncio.get_running_loop())


def cleanup_loop(loop_id: int) -> None:
    """Drop cached clients/semaphore for a loop that has been closed."""
    _anthropic_clients.pop(loop_id, None)
    _gemini_clients.pop(loop_id, None)
    _sems.pop(loop_id, None)


def _get_anthropic():
    """Per-loop lazy init of the Anthropic async client."""
    key = _loop_key()
    client = _anthropic_clients.get(key)
    if client is None:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        _anthropic_clients[key] = client
    return client


def _get_gemini():
    """Per-loop lazy init of the Google GenAI client.

    The SDK exposes both sync and async methods on one client; we use the
    async surface via ``client.aio.models.generate_content``.
    """
    key = _loop_key()
    client = _gemini_clients.get(key)
    if client is None:
        from google import genai

        client = genai.Client(api_key=settings.google_api_key)
        _gemini_clients[key] = client
    return client


def _get_sem() -> asyncio.Semaphore:
    key = _loop_key()
    sem = _sems.get(key)
    if sem is None:
        sem = asyncio.Semaphore(30)
        _sems[key] = sem
    return sem


# ──────────────────────────────────────────────────────────────────────
# Gemini → Anthropic adapter helpers
# ──────────────────────────────────────────────────────────────────────


def _anthropic_tools_to_gemini(tools: list[dict]):
    """Translate Anthropic-style tool specs into Gemini function declarations.

    Anthropic tool shape:  ``{name, description, input_schema}``
    Gemini tool shape:     ``Tool(function_declarations=[FunctionDeclaration(...)])``

    Cubist's tool schemas are JSON Schema, which Gemini's ``parameters``
    field accepts directly — no structural translation needed.
    """
    from google.genai import types

    decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters=t["input_schema"],
        )
        for t in tools
    ]
    return [types.Tool(function_declarations=decls)]


def _gemini_response_to_blocks(response) -> list:
    """Normalize a Gemini response into Anthropic-style content blocks.

    Each block is a ``SimpleNamespace`` quacking like an Anthropic
    ``ContentBlock``: attributes ``type``, ``text`` (for text blocks), or
    ``name`` + ``input`` (for tool_use blocks).
    """
    blocks: list[SimpleNamespace] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return blocks
    parts = getattr(candidates[0].content, "parts", None) or []
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc is not None:
            args = dict(fc.args) if fc.args else {}
            blocks.append(SimpleNamespace(type="tool_use", name=fc.name, input=args))
            continue
        text = getattr(part, "text", None)
        if text:
            blocks.append(SimpleNamespace(type="text", text=text))
    return blocks


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────


async def complete(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 256,
    tools: list[dict] | None = None,
) -> Any:
    """One-shot chat call routed through the configured provider.

    Returns a list of content blocks. For text replies, read
    ``content[0].text``. For tool-use replies, look for a block where
    ``block.type == "tool_use"`` and read ``block.name`` / ``block.input``.

    The same return shape is produced regardless of ``LLM_PROVIDER``.
    """
    tool_names = [t["name"] for t in tools] if tools else []
    log.info(
        "complete provider=%s model=%s prompt_chars=%d max_tokens=%d tools=%s",
        settings.llm_provider, model, len(user), max_tokens, tool_names,
    )
    t0 = time.monotonic()
    try:
        if settings.llm_provider == "gemini":
            blocks = await _complete_gemini(model, system, user, max_tokens, tools)
        else:
            blocks = await _complete_claude(model, system, user, max_tokens, tools)
    except Exception:
        log.exception(
            "complete failed after %.1fs provider=%s model=%s",
            time.monotonic() - t0, settings.llm_provider, model,
        )
        raise

    summary = _summarize_blocks(blocks)
    log.info(
        "complete ok in %.1fs provider=%s model=%s blocks=%s",
        time.monotonic() - t0, settings.llm_provider, model, summary,
    )
    return blocks


def _summarize_blocks(blocks: Any) -> list[str]:
    out: list[str] = []
    for b in blocks or []:
        t = getattr(b, "type", "?")
        if t == "text":
            text = getattr(b, "text", "") or ""
            out.append(f"text({len(text)}ch)")
        elif t == "tool_use":
            out.append(f"tool_use(name={getattr(b, 'name', '?')})")
        else:
            out.append(t)
    return out


async def complete_text(model: str, system: str, user: str, max_tokens: int = 256) -> str:
    """Convenience wrapper for plain-text replies.

    Returns the first text block's content, or ``""`` if no text block
    came back.
    """
    content = await complete(model, system, user, max_tokens=max_tokens)
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


# ──────────────────────────────────────────────────────────────────────
# Provider implementations
# ──────────────────────────────────────────────────────────────────────


async def _complete_claude(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    tools: list[dict] | None,
) -> Any:
    from anthropic._exceptions import APIError, RateLimitError

    client = _get_anthropic()
    backoff = 1.0
    async with _get_sem():
        for attempt in range(5):
            try:
                msg = await client.messages.create(
                    model=model,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    max_tokens=max_tokens,
                    tools=tools or [],
                )
                return msg.content
            except RateLimitError:
                await asyncio.sleep(backoff)
                backoff *= 2
            except APIError:
                if attempt == 4:
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
    raise RuntimeError("unreachable")


async def _complete_gemini(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    tools: list[dict] | None,
) -> Any:
    from google.genai import errors as genai_errors
    from google.genai import types

    client = _get_gemini()
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        # Gemini 2.5 Flash/Pro enable thinking by default, which consumes
        # output-token budget BEFORE any function_call is emitted. For a
        # builder that needs to return ~1-2k tokens of Python code, thinking
        # can eat the entire budget and we get an empty response. Disable it.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    if tools:
        config.tools = _anthropic_tools_to_gemini(tools)
        # Force the model to emit a function_call rather than free text.
        config.tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        )

    backoff = 1.0
    async with _get_sem():
        for attempt in range(5):
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=user,
                    config=config,
                )
                blocks = _gemini_response_to_blocks(response)
                if not blocks:
                    # Help diagnose "did not return tool_use" vs. truncation,
                    # safety blocks, or other silent empty-response states.
                    cand = (response.candidates[0]
                            if getattr(response, "candidates", None) else None)
                    fr = getattr(cand, "finish_reason", None)
                    safety = getattr(cand, "safety_ratings", None)
                    usage = getattr(response, "usage_metadata", None)
                    log.warning(
                        "gemini empty response model=%s finish_reason=%r "
                        "safety=%r usage=%r",
                        model, fr, safety, usage,
                    )
                return blocks
            except genai_errors.APIError as e:
                status = getattr(e, "code", None)
                if status == 429 or (attempt < 4):
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise
    raise RuntimeError("unreachable")
