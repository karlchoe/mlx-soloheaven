# SoloHeaven

SoloHeaven is an OpenAI-compatible chat server that sits in front of an upstream model runner such as vLLM. This branch is focused on Qwen3.5 deployments, especially `Qwen/Qwen3.5-0.8B`, with inference delegated to an external serving layer.

## What it provides

- OpenAI-compatible endpoints: `/v1/chat/completions` and `/v1/models`
- Built-in web chat UI at `/`
- Admin dashboard at `/admin`
- Local SQLite storage for sessions, messages, memories, and compaction history
- Multi-model routing by model name or alias
- Optional thinking controls for reasoning-capable Qwen models

The server acts as a proxy. Actual inference happens in your upstream OpenAI-compatible backend.

## Quick start

```bash
git clone https://github.com/joongom/mlx-soloheaven.git
cd mlx-soloheaven
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Start an upstream server first. Example with vLLM:

```bash
vllm serve Qwen/Qwen3.5-0.8B --port 8001 --max-model-len 262144
```

Then start SoloHeaven:

```bash
soloheaven \
  --openai-base-url http://127.0.0.1:8001/v1 \
  --model Qwen/Qwen3.5-0.8B
```

Or use the helper script:

```bash
./start_qwen3.5_0.8b.sh
```

## Configuration

All settings are available as CLI flags or `SOLOHEAVEN_*` environment variables. Important ones:

- `SOLOHEAVEN_OPENAI_BASE_URL`: upstream OpenAI-compatible base URL
- `SOLOHEAVEN_MODEL`: default upstream model ID
- `SOLOHEAVEN_MODELS`: comma-separated list such as `qwen35=Qwen/Qwen3.5-0.8B`
- `SOLOHEAVEN_THINKING_BUDGET`: max tokens allowed inside `<think>`

Copy [`.env.example`](.env.example) to `.env` for local development.

## Multi-model usage

```bash
soloheaven \
  --openai-base-url http://127.0.0.1:8001/v1 \
  --models qwen35=Qwen/Qwen3.5-0.8B qwen35-fast=Qwen/Qwen3.5-0.8B:no_think_tag
```

The first model becomes the default. Requests can target either the alias or the full model name.

## API example

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="unused")
response = client.chat.completions.create(
    model="Qwen/Qwen3.5-0.8B",
    messages=[{"role": "user", "content": "Explain rotary embeddings briefly."}],
)
print(response.choices[0].message.content)
```

## Project structure

- `src/mlx_soloheaven/api/`: OpenAI-compatible, web, settings, compaction, and admin routes
- `src/mlx_soloheaven/engine/openai_proxy_engine.py`: upstream proxy engine
- `src/mlx_soloheaven/storage/database.py`: SQLite persistence
- `src/mlx_soloheaven/web/`: built-in chat and admin UI

## Current scope

This branch is designed for OpenAI-compatible upstreams. If you want to run Qwen3.5 directly, use a serving layer such as vLLM and point SoloHeaven at that endpoint.
