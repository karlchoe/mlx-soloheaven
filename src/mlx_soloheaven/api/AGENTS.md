# API KNOWLEDGE

## OVERVIEW
HTTP surface area for three audiences: OpenAI-compatible clients, built-in web chat, and admin/session management.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| OpenAI-compatible behavior | `openai_compat.py` | `/v1/chat/completions`, `/v1/models`, session cache endpoints |
| Web chat/session CRUD | `chat.py` | `/api/sessions/*`, memories, cache stats |
| Admin dashboard data/SSE | `admin.py` | log stream, models, cache, DB, reset endpoints |
| Session tuning | `settings.py` | per-session sampling/context settings |
| Manual compaction endpoints | `compaction.py` | compaction trigger/history/status |
| Shared request/response models | `schemas.py` | OpenAI-compatible Pydantic types |

## CONVENTIONS
- Routers are split by product surface, not by HTTP verb.
- OpenAI-compatible models live in `schemas.py`; avoid redefining near-identical payload models inside route files.
- Streaming responses use SSE via `StreamingResponse`; keep chunk shape consistent with existing endpoints.
- `server.py` owns router registration and engine injection (`set_engines`, `set_engine`).

## ANTI-PATTERNS
- Do not put core cache/inference logic in route handlers; call engine/database helpers.
- Do not break OpenAI compatibility casually; README and client examples assume this is a drop-in backend.
- Do not add a new route family without deciding whether it belongs under `/v1`, `/api`, or `/api/admin`.
- Do not introduce silent payload shape drift between streaming and non-streaming responses.

## NOTES
- `chat.py` already mixes session CRUD, chat, memory, and cache stats; if extending it, preserve route grouping discipline.
- `admin.py` exposes destructive reset endpoints; treat that file as operationally sensitive.
