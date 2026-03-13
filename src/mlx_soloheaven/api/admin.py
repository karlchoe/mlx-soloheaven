"""Admin API for logs, model settings, session state, and DB overview."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Any, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from mlx_soloheaven.storage import database as db

router = APIRouter(prefix="/api/admin")

_engines: dict[str, Any] = {}
_default_engine: Any = None


def set_engines(engines: dict[str, Any], default: Any):
    global _engines, _default_engine
    _engines = engines
    _default_engine = default


class LogBuffer(logging.Handler):
    """Captures log records and broadcasts them to SSE subscribers."""

    def __init__(self, maxlen: int = 500):
        super().__init__()
        self.buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self.subscribers: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def emit(self, record: logging.LogRecord):
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": self.format(record),
        }
        self.buffer.append(entry)
        for queue in list(self.subscribers):
            try:
                if self._loop and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(queue.put_nowait, entry)
            except Exception:
                pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self.subscribers:
            self.subscribers.remove(queue)


log_buffer = LogBuffer()
log_buffer.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))


def install_log_handler():
    """Install the log buffer on the root logger."""
    root = logging.getLogger()
    log_buffer.setLevel(logging.DEBUG)
    root.addHandler(log_buffer)
    try:
        log_buffer.set_loop(asyncio.get_event_loop())
    except RuntimeError:
        pass


@router.get("/logs/stream")
async def stream_logs():
    """SSE endpoint for real-time log streaming."""
    log_buffer.set_loop(asyncio.get_event_loop())

    async def _generate() -> AsyncGenerator[str, None]:
        queue = log_buffer.subscribe()
        try:
            for entry in list(log_buffer.buffer)[-100:]:
                yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            log_buffer.unsubscribe(queue)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/logs/recent")
async def recent_logs(limit: int = 200):
    """Get recent log entries."""
    return list(log_buffer.buffer)[-limit:]


@router.get("/models")
async def models_overview():
    """List loaded models with their default parameters."""
    models = []
    for model_id, engine in _engines.items():
        cfg = engine.cfg
        models.append(
            {
                "model_id": model_id,
                "backend": "openai-compatible",
                "model_path": cfg.model_path,
                "openai_base_url": cfg.openai_base_url,
                "defaults": {
                    "temperature": cfg.default_temperature,
                    "top_p": cfg.default_top_p,
                    "min_p": cfg.default_min_p,
                    "top_k": cfg.default_top_k,
                    "repetition_penalty": cfg.default_repetition_penalty,
                    "max_tokens": cfg.default_max_tokens,
                },
                "thinking": {
                    "enabled": cfg.enable_thinking,
                    "budget": cfg.thinking_budget,
                },
                "sessions": len(engine._sessions),
            }
        )
    return {"models": models}


@router.get("/cache")
async def cache_overview():
    """Return active session metadata for each engine."""
    result = {
        "engines": {},
        "disk_files": [],
        "total_memory_gb": 0.0,
        "total_disk_gb": 0.0,
    }

    for model_id, engine in _engines.items():
        sessions = []
        for session_id, state in engine._sessions.items():
            sessions.append(
                {
                    "session_id": session_id,
                    "messages": len(state.messages),
                    "cache_tokens": getattr(state, "total_cache_tokens", 0),
                    "cache_size_mb": 0.0,
                    "last_used": state.last_used,
                    "age_s": round(time.time() - state.last_used, 0),
                }
            )
        sessions.sort(key=lambda item: item["last_used"], reverse=True)

        result["engines"][model_id] = {
            "model_id": engine.model_id,
            "provider_url": engine.cfg.openai_base_url,
            "enable_thinking": engine.cfg.enable_thinking,
            "sessions": sessions,
            "session_count": len(sessions),
            "base_caches": [],
            "cache_manager": engine.cache_manager.stats(),
        }

    return result


@router.get("/db")
async def db_overview():
    """Database tables overview."""
    async with db.get_db() as conn:
        sessions = await conn.execute_fetchall(
            "SELECT s.id, s.title, s.created_at, s.updated_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) as msg_count "
            "FROM sessions s ORDER BY s.updated_at DESC"
        )
        session_list = [dict(row) for row in sessions]

        msg_stats = await conn.execute_fetchall("SELECT role, COUNT(*) as cnt FROM messages GROUP BY role")
        msg_summary = {row["role"]: row["cnt"] for row in msg_stats}

        total_sessions = len(session_list)
        total_messages = await conn.execute_fetchall("SELECT COUNT(*) as cnt FROM messages")
        total_memories = await conn.execute_fetchall("SELECT COUNT(*) as cnt FROM memories")

        db_size = 0
        if db._db_path and os.path.exists(db._db_path):
            db_size = os.path.getsize(db._db_path)

    return {
        "db_path": db._db_path,
        "db_size_mb": round(db_size / 1e6, 2),
        "total_sessions": total_sessions,
        "total_messages": total_messages[0]["cnt"] if total_messages else 0,
        "total_memories": total_memories[0]["cnt"] if total_memories else 0,
        "message_by_role": msg_summary,
        "sessions": session_list,
    }


@router.post("/cache/reset")
async def reset_cache():
    """Clear in-memory session state held by the proxy layer."""
    cleared = {"memory_sessions": 0, "disk_files": 0, "base_caches": 0}

    for engine in _engines.values():
        cleared["memory_sessions"] += len(engine._sessions)
        engine._sessions.clear()

        base_caches = getattr(engine, "_base_caches", None)
        if isinstance(base_caches, dict):
            cleared["base_caches"] += len(base_caches)
            base_caches.clear()

        memory_caches = getattr(engine.cache_manager, "memory_caches", None)
        if hasattr(memory_caches, "clear"):
            memory_caches.clear()

        disk_index = getattr(engine.cache_manager, "disk_index", None)
        if hasattr(disk_index, "clear"):
            disk_index.clear()

    return {"status": "ok", "cleared": cleared}


@router.post("/db/reset")
async def reset_db():
    """Clear all data from DB tables."""
    async with db.get_db() as conn:
        await conn.execute("DELETE FROM messages")
        await conn.execute("DELETE FROM sessions")
        await conn.execute("DELETE FROM memories")
        await conn.commit()
    return {"status": "ok"}


@router.post("/reset-all")
async def reset_all():
    """Clear both in-memory session state and database data."""
    cache_result = await reset_cache()
    await reset_db()
    return {"status": "ok", "sessions": cache_result["cleared"], "db": "cleared"}
