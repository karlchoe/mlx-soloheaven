# SoloHeaven Reverse Engineering Notes

## What this branch actually is

This branch is not a local MLX inference server. It is a FastAPI application that proxies chat requests to an upstream OpenAI-compatible backend and adds local session storage, a browser UI, admin endpoints, and lightweight conversation compaction.

Primary evidence:

- `README.md` describes the server as a proxy in front of vLLM or another OpenAI-compatible backend.
- `pyproject.toml` depends on `fastapi`, `httpx`, `uvicorn`, `aiosqlite`, `pydantic`, and `python-dotenv`; there is no MLX dependency.
- `src/mlx_soloheaven/server.py` instantiates `OpenAIProxyEngine`, not a local inference engine.
- `src/mlx_soloheaven/engine/openai_proxy_engine.py` only talks to an upstream HTTP API.

Note: the generated `AGENTS.md` files in this repo still mention the older MLX/Apple Silicon architecture. Those notes do not match the current branch.

## Runtime entrypoints

### Packaging and CLI

- Console script: `soloheaven = "mlx_soloheaven.cli:main"` in `pyproject.toml`
- Module entry: `python -m mlx_soloheaven` via `src/mlx_soloheaven/__main__.py`
- Shell helpers: `start.sh` and `start_qwen3.5_0.8b.sh`

### Startup chain

1. `src/mlx_soloheaven/cli.py`
   - Parses CLI args and `SOLOHEAVEN_*` env vars
   - Requires `--openai-base-url`
   - Builds a `Config` via `Config.from_args()`
2. `src/mlx_soloheaven/server.py`
   - Creates one `OpenAIProxyEngine` per configured model
   - Initializes SQLite
   - Calls `engine.load_model()` to probe upstream `/v1/models`
   - Registers API routers and mounts static web assets
3. `uvicorn.run(...)`
   - Serves web UI, admin UI, and OpenAI-compatible API from one process

## Module map

### Core application

- `src/mlx_soloheaven/cli.py`
  - User-facing runtime options
  - Input validation for model and upstream base URL
- `src/mlx_soloheaven/config.py`
  - Dataclasses for global config and per-model config
  - Multi-model parsing (`alias=model-id`, optional `:no_think_tag`)
- `src/mlx_soloheaven/server.py`
  - FastAPI app factory
  - Router registration and dependency wiring

### Engine layer

- `src/mlx_soloheaven/engine/openai_proxy_engine.py`
  - Core proxy engine
  - Builds OpenAI-compatible payloads
  - Handles sync and streaming upstream calls
  - Tracks in-memory session message history for local resume semantics
- `src/mlx_soloheaven/engine/tool_parser.py`
  - Converts tool-call XML/text conventions to and from OpenAI tool-call shape
- `src/mlx_soloheaven/engine/compaction.py`
  - Summarizes older conversation turns using the same upstream backend

### API layer

- `src/mlx_soloheaven/api/openai_compat.py`
  - `/v1/chat/completions`
  - `/v1/models`
  - Proxy-session introspection endpoints
- `src/mlx_soloheaven/api/chat.py`
  - Browser-oriented session CRUD
  - SSE chat streaming endpoint
  - Memory endpoints and cache stats
- `src/mlx_soloheaven/api/settings.py`
  - Per-session generation settings
- `src/mlx_soloheaven/api/compaction.py`
  - Manual compaction endpoints and status/history
- `src/mlx_soloheaven/api/admin.py`
  - Log streaming, model overview, DB overview, reset operations

### Storage and frontend

- `src/mlx_soloheaven/storage/database.py`
  - SQLite schema creation and simple migrations
  - Sessions, messages, memories, compactions
- `src/mlx_soloheaven/web/index.html`
  - Main browser chat UI shell
- `src/mlx_soloheaven/web/admin.html`
  - Admin dashboard shell
- `src/mlx_soloheaven/web/app.js`
  - Main browser behavior for sessions, chat, settings, and streaming updates

## Data model

The SQLite database contains four main tables:

- `sessions`
  - Title, system prompt, generation settings, context limit, compaction metadata, total token estimate
- `messages`
  - Role, content, tool calls, tool call ID, thinking text, token count, stats blob
- `memories`
  - Lightweight long-term memory items keyed by category and importance
- `compactions`
  - History of prompt-compaction events and generated summaries

Observations:

- Migrations are handled with repeated `ALTER TABLE ... ADD COLUMN` guarded by `try/except`.
- `total_prompt_tokens` is stored on `sessions` but can fall back to summing message token counts.
- There is no ORM; storage is direct SQL through `aiosqlite`.

## Known mismatches and unfinished edges

- Generated `AGENTS.md` files still describe the old MLX/Apple Silicon engine, but the active branch uses `OpenAIProxyEngine`.
- `api/settings.py` accepts `top_p`, `min_p`, `top_k`, and `repetition_penalty`, and `api/chat.py` reads them from the session record, but the `sessions` schema shown in `storage/database.py` does not currently create those columns.
- `engine/openai_proxy_engine.py` exposes local session/cache-style introspection, but `NullCacheManager` and `supports_prefix_cache = False` make it metadata-only rather than real prompt-cache reuse.
- `storage/database.py:update_session_compacted_state(...)` is a stub, so compaction history is recorded without a full persisted-history rewrite path.

## Request surfaces

### OpenAI-compatible API

- `POST /v1/chat/completions`
- `GET /v1/models`
- `POST /v1/sessions/{session_id}/compact`
- `GET /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `DELETE /v1/sessions/{session_id}`

### Browser/API routes

- `POST /api/sessions`
- `GET /api/sessions`
- `GET /api/sessions/{session_id}`
- `PATCH /api/sessions/{session_id}`
- `DELETE /api/sessions/{session_id}`
- `GET /api/sessions/{session_id}/messages`
- `POST /api/sessions/{session_id}/chat`
- `GET/PATCH /api/sessions/{session_id}/settings`
- Compaction endpoints under `/api/sessions/{session_id}/...`
- Memory endpoints under `/api/memories...`
- Cache stats at `/api/cache/stats`
- Admin endpoints under `/api/admin/...`

## Operational model

This application owns:

- HTTP API surface
- Local persistence and session metadata
- Browser UI and admin UI
- Translation between browser/OpenAI client traffic and the upstream backend
- Lightweight local session cache metadata

This application does not own:

- Model loading into GPU/CPU memory
- Real token generation kernels
- Vendor-specific inference runtime

Those are delegated to the upstream OpenAI-compatible backend named by `openai_base_url`.

## Platform assumptions

The current branch is OS-independent at the application level:

- No MLX imports
- No Metal/macOS-specific APIs
- No CUDA-specific code in this repo
- Standard Python + bash startup only

That means WSL/Linux compatibility depends mainly on whether your chosen upstream backend runs there. The SoloHeaven proxy layer itself is portable.
