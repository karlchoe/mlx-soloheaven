# PACKAGE KNOWLEDGE

## OVERVIEW
Core package boundary for server bootstrap, config, inference engine, persistence, and embedded web UI.

## STRUCTURE
```text
src/mlx_soloheaven/
├── cli.py          # CLI/env parsing entry point
├── config.py       # Shared config dataclasses
├── server.py       # FastAPI factory and startup lifecycle
├── api/            # HTTP routers and Pydantic schemas
├── engine/         # MLX generation, thinking, compaction, tool parsing
├── cache/          # KV cache budget manager
├── storage/        # SQLite access layer
└── web/            # Static chat/admin assets
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| New runtime option | `cli.py` + `config.py` | Add flag/env parsing, then thread through `Config` |
| App startup ordering | `server.py` | DB init, model load, router engine registration all happen here |
| New API capability | `api/` | Router modules stay separate by audience/use case |
| Model behavior changes | `engine/` | Core generation/cache logic lives here |
| Session/cache persistence | `cache/` or `storage/` | Cache = KV tensors; storage = SQLite metadata/messages |
| Browser UX/admin changes | `web/` | No frontend build step |

## CONVENTIONS
- Keep package boundaries functional: API wrappers call into engine/storage instead of re-implementing core logic.
- `server.py` is the integration seam; new routers or engines should be wired there, not through hidden import side effects.
- `Config` is intentionally simple dataclass state, not a settings framework; follow that pattern unless there is a strong reason not to.
- `__main__.py` stays thin and only forwards to CLI main.

## ANTI-PATTERNS
- Do not scatter env var parsing across modules; keep runtime input normalization in `cli.py` and `config.py`.
- Do not add a separate frontend toolchain unless the static-asset approach is no longer viable.
- Do not duplicate model/session state in both API routers and engine internals; engine remains the authority.

## NOTES
- LSP was unavailable during generation; this file is based on direct code search and repo structure.
- No local test convention exists yet, so avoid documenting a fake one in child docs.
