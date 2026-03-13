# ENGINE KNOWLEDGE

## OVERVIEW
Inference core: MLX model loading, session/base-cache reuse, generation streaming, GPU keepalive, disk persistence, and compaction support.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Main inference/session flow | `mlx_engine.py` | Largest file; owns locks, sessions, cache reuse, disk flush |
| Compaction strategies | `compaction.py` | Strategy enum and compaction engine |
| Thinking token controls | `thinking.py` | Budget/logits processors |
| Tool-call translation | `tool_parser.py` | XML/OpenAI tool-call conversion |

## CONVENTIONS
- `mlx_engine.py` is the canonical source for session semantics and cache lifecycle.
- Global GPU coordination is intentional; new concurrency behavior must account for the shared lock.
- Disk persistence and idle-time flush behavior are part of normal operation, not optional extras.
- Hybrid-attention model constraints described in `README.md` are design constraints for engine changes.

## ANTI-PATTERNS
- Do not trim or partially slice cached thinking/history tokens; this repo explicitly documents that quality regresses.
- Do not replace full-prefix cache reuse with rotating-window shortcuts for Qwen hybrid attention models.
- Do not bypass the engine lock when adding generation or GPU-touching work.
- Do not treat README benchmark conclusions as stale without replacing them with new measurements.

## NOTES
- If you touch compaction, cache invalidation rules are the first thing to re-check.
- Large tool-result suffixes are a known TTFT hotspot; be suspicious of changes that increase suffix size.
- Session matching behavior is part of perceived latency; regressions there are user-visible even if generation quality stays high.
- `mlx_engine.py` is large enough that small, well-scoped edits are safer than cross-cutting rewrites.
