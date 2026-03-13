# PROJECT KNOWLEDGE BASE

**Generated:** 2026-03-13
**Commit:** 3ae3ede
**Branch:** main

## OVERVIEW
Single-user MLX/FastAPI inference server for Apple Silicon. Core value is session-based KV cache reuse with OpenAI-compatible APIs plus an embedded web/admin UI.

## STRUCTURE
```text
mlx-soloheaven/
├── src/mlx_soloheaven/   # Python package: CLI, server, engine, API, storage, web assets
├── examples/             # Client config examples
├── start.sh              # Default local launch wrapper
├── start_qwen3.5_397b.sh # 397B-specific launch wrapper
├── .env.example          # Canonical env var reference
└── pyproject.toml        # Build metadata, deps, console entry point, ruff config
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Run the server | `start.sh` | Activates `.venv`, sets a 50 GB memory budget, enables GPU keepalive |
| Change CLI flags/env parsing | `src/mlx_soloheaven/cli.py` | `SOLOHEAVEN_*` env vars, argparse wiring |
| Change runtime config model | `src/mlx_soloheaven/config.py` | `Config` and `ModelConfig` are the source of truth |
| Change app bootstrap | `src/mlx_soloheaven/server.py` | FastAPI creation, router registration, startup load order |
| Add/modify API endpoints | `src/mlx_soloheaven/api/` | Separate routers for OpenAI compat, web chat, admin, settings, compaction |
| Debug inference/cache behavior | `src/mlx_soloheaven/engine/mlx_engine.py` | Largest and most central file |
| Change cache eviction/persistence | `src/mlx_soloheaven/cache/manager.py` | Budget-based memory/disk LRU |
| Change DB/session persistence | `src/mlx_soloheaven/storage/database.py` | SQLite schema plus lightweight migrations |
| Change browser UI/admin | `src/mlx_soloheaven/web/` | Static assets served directly by FastAPI |

## CONVENTIONS
- Python `src/` layout; actual project root is this directory, not the parent workspace.
- Config priority: CLI args > `SOLOHEAVEN_*` env vars > code defaults.
- Startup is CLI-first: `mlx-soloheaven` -> `cli.py` -> `Config.from_args()` -> `server.run_server()`.
- Web assets are embedded under the Python package, not in a separate frontend project.
- No time-based cache TTL; eviction is budget-driven only.
- Python version is pinned via `.python-version` to `3.12.11`; Ruff targets `py311` with `line-length = 100`.
- No test tree or CI pipeline exists yet; `pytest`, `httpx`, and `ruff` are available only as dev dependencies.

## ANTI-PATTERNS (THIS PROJECT)
- Do not replace the original system prompt during compaction; append summaries at the end or you invalidate the full cache prefix.
- Do not trim `<think>` tokens from cached history; the README documents measurable quality regressions.
- Do not introduce rotating/partial cache reuse for hybrid-attention models here; DeltaNet state makes cache reuse effectively all-or-nothing.
- Do not reuse one session ID across unrelated conversations; cache matching falls back to retry/full reprocessing.
- Do not assume tests/CI exist elsewhere in the repo; there are currently none.

## UNIQUE STYLES
- Research findings in `README.md` are part of the implementation contract, not marketing copy; performance caveats there matter.
- OpenAI compatibility is first-class: `/v1/chat/completions`, `/v1/models`, streaming SSE, `developer` role handling, tool call translation.
- Convenience scripts reflect realistic local deployment patterns; keep them aligned with CLI behavior.

## COMMANDS
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[dev]"
mlx-soloheaven --model /path/to/model
./start.sh
./start_qwen3.5_397b.sh
ruff check .
pytest
```

## NOTES
- These generated `AGENTS.md` files are now the only local instruction docs in the repo; there is still no `CLAUDE.md`, `CONTRIBUTING.md`, or CI workflow.
- `README.md` is unusually authoritative: architecture, API surface, cache rules, and failure cases are documented there in detail.
- `examples/opencode.json` is the only shipped client integration example.
