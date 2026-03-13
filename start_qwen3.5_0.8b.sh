#!/bin/bash
# Start SoloHeaven against an OpenAI-compatible backend serving Qwen3.5-0.8B.
set -euo pipefail

OPENAI_BASE_URL="${SOLOHEAVEN_OPENAI_BASE_URL:-http://127.0.0.1:8001/v1}"
MODEL_ID="${SOLOHEAVEN_MODEL:-Qwen/Qwen3.5-0.8B}"

cd "$(dirname "$0")"
source .venv/bin/activate

soloheaven \
  --openai-base-url "$OPENAI_BASE_URL" \
  --model "$MODEL_ID" \
  "$@"
