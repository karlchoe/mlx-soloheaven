"""OpenAI-compatible API endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from mlx_soloheaven.api.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChunkChoice,
    DeltaMessage,
    FunctionCall,
    ModelInfo,
    ModelListResponse,
    ResponseMessage,
    ToolCall,
    UsageInfo,
)
from mlx_soloheaven.engine.tool_parser import (
    parse_tool_calls,
    split_thinking_and_content,
    strip_thinking_tags,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_engines: dict[str, Any] = {}
_default_engine: Any = None


def set_engines(engines: dict[str, Any], default: Any):
    global _engines, _default_engine
    _engines = engines
    _default_engine = default


def _get_engine(model: str):
    """Resolve model name to engine by exact match or substring match."""
    if model in _engines:
        return _engines[model]
    model_lower = model.lower()
    for key, engine in _engines.items():
        if model_lower in key.lower() or model_lower in engine.model_id.lower():
            return engine
    return _default_engine


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    engine = _get_engine(request.model)

    preview = []
    for message in request.messages[:3]:
        raw = message.content
        if isinstance(raw, list):
            content = str(raw)[:80]
        else:
            content = (raw or "")[:80].replace("\n", "\\n")
        preview.append(f"{message.role}:{content!r}")
    preview_str = " | ".join(preview)
    if len(request.messages) > 3:
        preview_str += f" | ...+{len(request.messages) - 3} more"

    logger.info(
        "[Request] user=%r, model=%s -> %s, stream=%s, thinking=%s, max_tokens=%s, messages=%s | %s",
        request.user,
        request.model,
        engine.model_id,
        request.stream,
        request.thinking,
        request.max_tokens or request.max_completion_tokens,
        len(request.messages),
        preview_str,
    )

    if request.stream:
        return StreamingResponse(
            _stream_completion(request, engine),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return _sync_completion(request, engine)


def _map_repetition_penalty(request: ChatCompletionRequest) -> float | None:
    repetition_penalty = request.repetition_penalty
    if repetition_penalty is None and (request.frequency_penalty or request.presence_penalty):
        frequency_penalty = request.frequency_penalty or 0.0
        presence_penalty = request.presence_penalty or 0.0
        repetition_penalty = 1.0 + (frequency_penalty + presence_penalty) * 0.25
    return repetition_penalty


def _sync_completion(request: ChatCompletionRequest, engine: Any) -> ChatCompletionResponse:
    messages = strip_thinking_tags([message.model_dump(exclude_none=True) for message in request.messages])
    tools = [tool.model_dump() for tool in request.tools] if request.tools else None

    result = engine.complete(
        messages,
        max_tokens=request.max_tokens or request.max_completion_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        min_p=request.min_p,
        top_k=request.top_k,
        repetition_penalty=_map_repetition_penalty(request),
        tools=tools,
        session_id=request.user,
        thinking=request.thinking if request.thinking is not None else engine.cfg.enable_thinking,
        thinking_budget=request.thinking_budget,
    )

    message = ResponseMessage(content=result.content)
    if result.tool_calls:
        message.tool_calls = [
            ToolCall(
                id=tool_call["id"],
                function=FunctionCall(
                    name=tool_call["function"]["name"],
                    arguments=tool_call["function"]["arguments"],
                ),
            )
            for tool_call in result.tool_calls
        ]

    if request.user:
        engine.update_session_messages(
            request.user,
            messages + [{"role": "assistant", "content": result.content or ""}],
        )

    return ChatCompletionResponse(
        model=request.model,
        choices=[Choice(message=message, finish_reason=result.finish_reason)],
        usage=UsageInfo(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.prompt_tokens + result.completion_tokens,
            cache_info=result.cache_info,
        ),
    )


async def _stream_completion(
    request: ChatCompletionRequest,
    engine: Any,
) -> AsyncGenerator[str, None]:
    messages = strip_thinking_tags([message.model_dump(exclude_none=True) for message in request.messages])
    tools = [tool.model_dump() for tool in request.tools] if request.tools else None
    has_tools = bool(tools)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    model = request.model

    first_chunk = ChatCompletionChunk(
        id=chunk_id,
        created=created,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(role="assistant"))],
    )
    yield f"data: {first_chunk.model_dump_json(exclude_none=True)}\n\n"

    enable_thinking = request.thinking if request.thinking is not None else engine.cfg.enable_thinking
    if enable_thinking and getattr(engine, "inject_initial_think_tag", True):
        yield f"data: {_make_content_chunk(chunk_id, created, model, '<think>\\n')}\n\n"

    accumulated_text = ""
    tool_call_buffer = ""
    in_tool_call = False
    final_prompt_tokens = 0
    final_completion_tokens = 0
    final_cache_info = None
    holdback = ""
    tool_call_tag = "<tool_call>"

    async for result in engine.generate_stream_async(
        messages,
        max_tokens=request.max_tokens or request.max_completion_tokens,
        temperature=request.temperature,
        top_p=request.top_p,
        min_p=request.min_p,
        top_k=request.top_k,
        repetition_penalty=_map_repetition_penalty(request),
        session_id=request.user,
        tools=tools,
        thinking=enable_thinking,
        thinking_budget=request.thinking_budget,
    ):
        if result.finish_reason is not None:
            final_prompt_tokens = result.prompt_tokens
            final_completion_tokens = result.completion_tokens
            final_cache_info = result.cache_info
            break

        if not result.text:
            yield ": keepalive\n\n"
            continue

        accumulated_text += result.text

        if in_tool_call:
            tool_call_buffer += result.text
            continue

        holdback += result.text

        if has_tools and tool_call_tag.startswith(holdback.lstrip()):
            continue

        if has_tools and tool_call_tag in holdback:
            index = holdback.index(tool_call_tag)
            before = holdback[:index]
            if before:
                yield f"data: {_make_content_chunk(chunk_id, created, model, before)}\n\n"
            in_tool_call = True
            tool_call_buffer = holdback[index:]
            holdback = ""
            continue

        if holdback:
            yield f"data: {_make_content_chunk(chunk_id, created, model, holdback)}\n\n"
            holdback = ""

    if holdback and not in_tool_call:
        yield f"data: {_make_content_chunk(chunk_id, created, model, holdback)}\n\n"

    finish_reason = "stop"
    if tool_call_buffer:
        _, tool_calls = parse_tool_calls(tool_call_buffer)
        if tool_calls:
            finish_reason = "tool_calls"
            for index, tool_call in enumerate(tool_calls):
                name_chunk = ChatCompletionChunk(
                    id=chunk_id,
                    created=created,
                    model=model,
                    choices=[
                        ChunkChoice(
                            delta=DeltaMessage(
                                tool_calls=[
                                    {
                                        "index": index,
                                        "id": tool_call["id"],
                                        "type": "function",
                                        "function": {
                                            "name": tool_call["function"]["name"],
                                            "arguments": "",
                                        },
                                    }
                                ]
                            )
                        )
                    ],
                )
                yield f"data: {name_chunk.model_dump_json(exclude_none=True)}\n\n"

                args_chunk = ChatCompletionChunk(
                    id=chunk_id,
                    created=created,
                    model=model,
                    choices=[
                        ChunkChoice(
                            delta=DeltaMessage(
                                tool_calls=[
                                    {
                                        "index": index,
                                        "function": {
                                            "arguments": tool_call["function"]["arguments"],
                                        },
                                    }
                                ]
                            )
                        )
                    ],
                )
                yield f"data: {args_chunk.model_dump_json(exclude_none=True)}\n\n"

    if request.user:
        _, content = split_thinking_and_content(accumulated_text)
        engine.update_session_messages(
            request.user,
            messages + [{"role": "assistant", "content": content or ""}],
        )

    final_chunk = ChatCompletionChunk(
        id=chunk_id,
        created=created,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(), finish_reason=finish_reason)],
        usage=UsageInfo(
            prompt_tokens=final_prompt_tokens,
            completion_tokens=final_completion_tokens,
            total_tokens=final_prompt_tokens + final_completion_tokens,
            cache_info=final_cache_info,
        ),
    )
    yield f"data: {final_chunk.model_dump_json(exclude_none=True)}\n\n"
    yield "data: [DONE]\n\n"


def _make_content_chunk(chunk_id: str, created: int, model: str, text: str) -> str:
    return ChatCompletionChunk(
        id=chunk_id,
        created=created,
        model=model,
        choices=[ChunkChoice(delta=DeltaMessage(content=text))],
    ).model_dump_json(exclude_none=True)


@router.get("/v1/models")
async def list_models():
    return ModelListResponse(data=[ModelInfo(id=engine.model_id) for engine in _engines.values()])


class CompactRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/v1/sessions/{session_id}/compact")
async def compact_session(session_id: str, request: CompactRequest):
    """Replace the stored session message history after compaction."""
    messages = [message.model_dump(exclude_none=True) for message in request.messages]
    return _default_engine.compact_session(session_id, messages)


@router.get("/v1/sessions")
async def list_sessions():
    """List all active sessions."""
    return {
        "sessions": {model_id: engine.list_sessions() for model_id, engine in _engines.items()},
        "base_caches": {model_id: engine.base_cache_stats() for model_id, engine in _engines.items()},
    }


@router.get("/v1/sessions/{session_id}")
async def get_session(session_id: str):
    """Get session details."""
    info = _default_engine.get_session(session_id)
    if not info:
        return JSONResponse(status_code=404, content={"error": "session not found"})
    return info


@router.delete("/v1/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session."""
    _default_engine.delete_session(session_id)
    return {"status": "ok", "session_id": session_id}
