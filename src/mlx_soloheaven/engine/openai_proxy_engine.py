"""OpenAI-compatible proxy engine."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

import httpx

from mlx_soloheaven.config import Config
from mlx_soloheaven.engine.tool_parser import split_thinking_and_content

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """A single token/chunk from generation."""

    text: str = ""
    token: int = 0
    finish_reason: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tps: float = 0.0
    generation_tps: float = 0.0
    status: Optional[str] = None
    cache_info: Optional[dict] = None


@dataclass
class CompletionResult:
    """Full completion result after generation finishes."""

    content: Optional[str] = None
    thinking: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_tps: float = 0.0
    generation_tps: float = 0.0
    cache_info: Optional[dict] = None


@dataclass
class SessionState:
    """Tracks message history for proxied sessions."""

    messages: list[dict]
    last_used: float = field(default_factory=time.time)
    total_cache_tokens: int = 0
    cache: None = None

    def touch(self):
        self.last_used = time.time()


class NullCacheManager:
    """Minimal cache-manager shim for proxied backends."""

    def stats(self) -> dict:
        return {
            "memory_caches": 0,
            "memory_usage_gb": 0.0,
            "memory_budget_gb": 0.0,
            "disk_caches": 0,
            "disk_usage_gb": 0.0,
            "disk_budget_gb": 0.0,
        }

    def _estimate_cache_size(self, cache: Any) -> int:
        return 0


class OpenAIProxyEngine:
    """Route generation to an external OpenAI-compatible backend."""

    inject_initial_think_tag = False
    supports_prefix_cache = False

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.model = None
        self.tokenizer = None
        self._lock = threading.Lock()
        self.cache_manager = NullCacheManager()
        self.model_id = cfg.model_alias or os.path.basename(cfg.model_path.rstrip("/")) or cfg.model_path
        self._sessions: dict[str, SessionState] = {}
        self._base_caches: dict[str, dict] = {}

    def _api_root(self) -> str:
        base = self.cfg.openai_base_url.rstrip("/")
        if base.endswith("/v1"):
            return base
        return f"{base}/v1"

    def _endpoint(self, path: str) -> str:
        return f"{self._api_root()}{path}"

    def _headers(self) -> dict[str, str]:
        key = self.cfg.openai_api_key or "EMPTY"
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _extract_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts)
        return ""

    @staticmethod
    def _messages_match(stored: list[dict], incoming: list[dict]) -> bool:
        if len(incoming) < len(stored):
            return False
        for idx, s_msg in enumerate(stored):
            i_msg = incoming[idx]
            if s_msg.get("role") != i_msg.get("role"):
                return False
            if OpenAIProxyEngine._extract_text(s_msg.get("content")) != OpenAIProxyEngine._extract_text(
                i_msg.get("content")
            ):
                return False
        return True

    def _has_disk_cache(self, session_id: str) -> bool:
        return False

    def _load_session_from_disk(self, session_id: str):
        return None

    def load_model(self):
        if not self.cfg.openai_base_url:
            raise ValueError("openai_base_url is required")

        logger.info(
            f"[{self.model_id}] Using OpenAI-compatible backend at {self._api_root()}"
        )

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(self._endpoint("/models"), headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
            model_ids = [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]
            if model_ids and not any(self.cfg.model_path.lower() in mid.lower() for mid in model_ids):
                logger.warning(
                    f"[{self.model_id}] upstream /models does not list {self.cfg.model_path!r}; "
                    f"available={model_ids}"
                )
        except Exception as exc:
            logger.warning(f"[{self.model_id}] upstream probe failed: {exc}")

    def _build_payload(
        self,
        messages: list[dict],
        *,
        stream: bool,
        max_tokens: int | None,
        temperature: float | None,
        top_p: float | None,
        min_p: float | None,
        top_k: int | None,
        repetition_penalty: float | None,
        tools: list | None,
        session_id: str | None,
        thinking: bool | None,
        thinking_budget: int | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.cfg.model_path,
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if min_p is not None:
            payload["min_p"] = min_p
        if top_k is not None:
            payload["top_k"] = top_k
        if repetition_penalty is not None:
            payload["repetition_penalty"] = repetition_penalty
        if tools:
            payload["tools"] = tools
        if session_id:
            payload["user"] = session_id
        if thinking is not None:
            payload["enable_thinking"] = thinking
        if thinking_budget is not None:
            payload["thinking_budget"] = thinking_budget
        return payload

    @staticmethod
    def _final_cache_info() -> dict[str, Any]:
        return {
            "cache_mode": "proxy",
            "backend": "openai",
            "cached_tokens": 0,
        }

    @staticmethod
    def _tool_calls_to_xml(tool_calls: list[dict]) -> str:
        blocks: list[str] = []
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or "tool"
            args_text = fn.get("arguments") or "{}"
            try:
                parsed_args = json.loads(args_text)
            except (json.JSONDecodeError, TypeError):
                parsed_args = {}

            params = []
            for key, value in parsed_args.items():
                if isinstance(value, str):
                    value_text = value
                else:
                    value_text = json.dumps(value, ensure_ascii=False)
                params.append(f"<parameter={key}>{value_text}</parameter>")
            blocks.append(f"<tool_call><function={name}>{''.join(params)}</function></tool_call>")
        return "".join(blocks)

    @staticmethod
    def _normalize_tool_calls(tool_calls: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for idx, tc in enumerate(tool_calls):
            fn = tc.get("function") or {}
            normalized.append(
                {
                    "id": tc.get("id") or f"call_proxy_{idx}",
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    },
                }
            )
        return normalized

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        min_p: float | None = None,
        top_k: int | None = None,
        repetition_penalty: float | None = None,
        tools: list | None = None,
        session_id: str | None = None,
        thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> CompletionResult:
        payload = self._build_payload(
            messages,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            min_p=min_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            tools=tools,
            session_id=session_id,
            thinking=thinking,
            thinking_budget=thinking_budget,
        )
        with self._lock, httpx.Client(timeout=None) as client:
            resp = client.post(
                self._endpoint("/chat/completions"),
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = self._extract_text(message.get("content"))
        thinking_text, content_text = split_thinking_and_content(content)
        tool_calls = message.get("tool_calls") or []
        usage = data.get("usage") or {}
        return CompletionResult(
            content=content_text or None,
            thinking=thinking_text,
            tool_calls=self._normalize_tool_calls(tool_calls) if tool_calls else None,
            finish_reason=choice.get("finish_reason") or "stop",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cache_info=self._final_cache_info(),
        )

    async def generate_stream_async(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        min_p: float | None = None,
        top_k: int | None = None,
        repetition_penalty: float | None = None,
        session_id: str | None = None,
        tools: list | None = None,
        thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> AsyncGenerator[GenerationResult, None]:
        yield GenerationResult(status="generating")

        payload = self._build_payload(
            messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            min_p=min_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            tools=tools,
            session_id=session_id,
            thinking=thinking,
            thinking_budget=thinking_budget,
        )

        usage: dict[str, Any] = {}
        finish_reason = "stop"
        tool_calls: dict[int, dict[str, Any]] = {}
        tool_calls_emitted = False

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                self._endpoint("/chat/completions"),
                headers=self._headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    if not raw_line:
                        continue
                    if raw_line.startswith(":"):
                        continue
                    if not raw_line.startswith("data:"):
                        continue

                    data = raw_line[5:].strip()
                    if data == "[DONE]":
                        break

                    obj = json.loads(data)
                    if obj.get("usage"):
                        usage = obj["usage"]

                    for choice in obj.get("choices", []):
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield GenerationResult(text=content)
                        elif isinstance(content, list):
                            text = self._extract_text(content)
                            if text:
                                yield GenerationResult(text=text)

                        for tc in delta.get("tool_calls") or []:
                            index = tc.get("index", 0)
                            entry = tool_calls.setdefault(
                                index,
                                {
                                    "id": tc.get("id") or f"call_proxy_{index}",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if tc.get("id"):
                                entry["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                entry["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                entry["function"]["arguments"] += fn["arguments"]

                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]

                        if finish_reason == "tool_calls" and tool_calls and not tool_calls_emitted:
                            ordered = [tool_calls[idx] for idx in sorted(tool_calls)]
                            yield GenerationResult(text=self._tool_calls_to_xml(ordered))
                            tool_calls_emitted = True

        if finish_reason == "tool_calls" and tool_calls and not tool_calls_emitted:
            ordered = [tool_calls[idx] for idx in sorted(tool_calls)]
            yield GenerationResult(text=self._tool_calls_to_xml(ordered))

        yield GenerationResult(
            text="",
            finish_reason=finish_reason,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            cache_info=self._final_cache_info(),
        )

    def update_session_messages(self, session_id: str, messages: list[dict]):
        if not session_id:
            return
        session = self._sessions.get(session_id)
        if session is None:
            session = SessionState(messages=messages)
            self._sessions[session_id] = session
        else:
            session.messages = messages
            session.touch()

    def compact_session(self, session_id: str, messages: list[dict]) -> dict:
        self._sessions[session_id] = SessionState(messages=messages)
        return {
            "session_id": session_id,
            "status": "ok",
            "cached_tokens": 0,
            "previous_tokens": 0,
            "base_tokens": 0,
            "processing_time_ms": 0,
        }

    def base_cache_stats(self) -> list[dict]:
        return []

    def list_sessions(self) -> list[dict]:
        result = []
        for sid, session in self._sessions.items():
            result.append(
                {
                    "session_id": sid,
                    "messages": len(session.messages),
                    "cache_tokens": 0,
                    "last_used": session.last_used,
                }
            )
        return sorted(result, key=lambda item: item["last_used"], reverse=True)

    def get_session(self, session_id: str) -> dict | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        return {
            "session_id": session_id,
            "messages": len(session.messages),
            "cache_tokens": 0,
            "last_used": session.last_used,
        }

    def delete_session(self, session_id: str) -> bool:
        self._sessions.pop(session_id, None)
        return True

    def session_stats(self) -> dict:
        return {
            "active_sessions": len(self._sessions),
            "sessions": {
                sid: {
                    "messages": len(session.messages),
                    "cache_tokens": 0,
                    "last_used": session.last_used,
                }
                for sid, session in self._sessions.items()
            },
        }
