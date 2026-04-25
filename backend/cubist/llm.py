"""Shared LLM client. Person E owns; A and C use it.

Single shared async client + global semaphore + retry. Every LLM call in
the system goes through here so we have one place to tune concurrency and
rate-limit handling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from anthropic._exceptions import APIError as AnthropicAPIError
from anthropic._exceptions import RateLimitError
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from cubist.config import settings

_anthropic_client: AsyncAnthropic | None = None
_gemini_client: genai.Client | None = None
_sem = asyncio.Semaphore(settings.resolved_llm_max_concurrency)


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str | None = None
    type: str = "tool_use"


def _provider_for_model(model: str) -> str:
    if settings.llm_provider != "auto":
        return settings.llm_provider

    normalized = model.removeprefix("models/")
    if normalized.startswith("gemini-"):
        return "gemini"
    if normalized.startswith("claude-"):
        return "anthropic"
    return settings.resolved_llm_provider


def _get_anthropic_client() -> AsyncAnthropic:
    global _anthropic_client
    if not settings.anthropic_api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY or switch LLM_PROVIDER=gemini.")
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    api_key = settings.gemini_api_key or settings.google_api_key
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY for Gemini.")
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=api_key)
    return _gemini_client


def _gemini_tools(tools: list[dict] | None) -> list[genai_types.Tool] | None:
    if not tools:
        return None

    declarations = []
    for tool in tools:
        declarations.append(
            genai_types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description"),
                parameters_json_schema=tool.get("input_schema", {"type": "object"}),
            )
        )
    return [genai_types.Tool(function_declarations=declarations)]


def _gemini_tool_config(tools: list[dict] | None) -> genai_types.ToolConfig | None:
    if not tools:
        return None

    return genai_types.ToolConfig(
        function_calling_config=genai_types.FunctionCallingConfig(
            mode=genai_types.FunctionCallingConfigMode.ANY,
            allowed_function_names=[tool["name"] for tool in tools],
        )
    )


def _gemini_blocks(response: genai_types.GenerateContentResponse) -> list[TextBlock | ToolUseBlock]:
    blocks: list[TextBlock | ToolUseBlock] = []
    for candidate in response.candidates or []:
        if not candidate.content:
            continue
        for part in candidate.content.parts or []:
            if part.text:
                blocks.append(TextBlock(part.text))
            if part.function_call:
                function_call = part.function_call
                blocks.append(
                    ToolUseBlock(
                        name=function_call.name or "",
                        input=dict(function_call.args or {}),
                        id=getattr(function_call, "id", None),
                    )
                )
    if not blocks and response.text:
        blocks.append(TextBlock(response.text))
    return blocks


def _retry_gemini_error(error: genai_errors.APIError) -> bool:
    code = getattr(error, "code", None) or getattr(error, "status_code", None)
    return isinstance(error, genai_errors.ServerError) or code == 429


async def complete(
    model: str,
    system: str,
    user: str,
    max_tokens: int = 256,
    tools: list[dict] | None = None,
) -> Any:
    """One-shot chat call. Returns content blocks with Anthropic-compatible attrs.

    For text replies, take `content[0].text`. For tool-use replies, look for
    a `tool_use` block and read its `input` dict.
    """
    provider = _provider_for_model(model)
    if provider == "gemini":
        return await _complete_gemini(model, system, user, max_tokens, tools)
    return await _complete_anthropic(model, system, user, max_tokens, tools)


async def _complete_anthropic(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    tools: list[dict] | None,
) -> Any:
    client = _get_anthropic_client()
    backoff = 1.0
    async with _sem:
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
            except AnthropicAPIError:
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
) -> list[TextBlock | ToolUseBlock]:
    client = _get_gemini_client()
    config = genai_types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        system_instruction=system or None,
        tools=_gemini_tools(tools),
        tool_config=_gemini_tool_config(tools),
    )

    backoff = 1.0
    async with _sem:
        for attempt in range(5):
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=user,
                    config=config,
                )
                return _gemini_blocks(response)
            except genai_errors.APIError as error:
                if attempt == 4 or not _retry_gemini_error(error):
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
    raise RuntimeError("unreachable")


async def complete_text(model: str, system: str, user: str, max_tokens: int = 256) -> str:
    """Convenience wrapper for plain-text replies."""
    content = await complete(model, system, user, max_tokens=max_tokens)
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
