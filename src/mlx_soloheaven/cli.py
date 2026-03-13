"""Command-line interface for SoloHeaven."""

from __future__ import annotations

import argparse
import os


def _env(key: str, default: str | None = None) -> str | None:
    """Read from environment with SOLOHEAVEN_ prefix."""
    return os.environ.get(f"SOLOHEAVEN_{key}", default)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="soloheaven",
        description="OpenAI-compatible chat server for Qwen3.5 and other upstream models",
    )

    parser.add_argument(
        "--model",
        "-m",
        default=_env("MODEL"),
        help="Upstream model ID exposed by your OpenAI-compatible backend (env: SOLOHEAVEN_MODEL)",
    )

    models_env = _env("MODELS", "").strip()
    parser.add_argument(
        "--models",
        nargs="+",
        default=models_env.split(",") if models_env else None,
        help=(
            "Multiple upstream models: 'model-id' or 'alias=model-id', "
            "optional ':no_think_tag' suffix (env: SOLOHEAVEN_MODELS)"
        ),
    )
    parser.add_argument(
        "--openai-base-url",
        default=_env("OPENAI_BASE_URL", ""),
        help="Base URL for the upstream OpenAI-compatible backend (example: http://127.0.0.1:8001/v1)",
    )
    parser.add_argument(
        "--openai-api-key",
        default=_env("OPENAI_API_KEY", "EMPTY"),
        help="API key for the upstream backend (default: EMPTY)",
    )
    parser.add_argument(
        "--host",
        default=_env("HOST", "0.0.0.0"),
        help="Bind address (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(_env("PORT", "8000")),
        help="Listen port (default: 8000)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(_env("TEMPERATURE", "0.6")),
        help="Default sampling temperature (default: 0.6)",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=float(_env("TOP_P", "1.0")),
        help="Default nucleus sampling top-p (default: 1.0, disabled)",
    )
    parser.add_argument(
        "--min-p",
        type=float,
        default=float(_env("MIN_P", "0.0")),
        help="Default min-p sampling threshold (default: 0.0, disabled)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=int(_env("TOP_K", "0")),
        help="Default top-k sampling (default: 0, disabled)",
    )
    parser.add_argument(
        "--repetition-penalty",
        type=float,
        default=float(_env("REPETITION_PENALTY", "1.0")),
        help="Default repetition penalty (default: 1.0, disabled)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(_env("MAX_TOKENS", "32768")),
        help="Default max generation tokens (default: 32768)",
    )
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=int(_env("THINKING_BUDGET", "8192")),
        help="Max thinking tokens before forcing </think> (default: 8192, 0=unlimited)",
    )
    parser.add_argument(
        "--data-dir",
        default=_env("DATA_DIR", "./data"),
        help="Directory for the SQLite database and local session metadata (default: ./data)",
    )
    parser.add_argument(
        "--no-thinking",
        action="store_true",
        help="Disable thinking mode globally (default: enabled)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=_env("VERBOSE", "").lower() in ("1", "true", "yes"),
        help="Enable verbose logging (env: SOLOHEAVEN_VERBOSE)",
    )

    args = parser.parse_args(argv)

    if not args.model and not args.models:
        parser.error(
            "Model ID is required. Set --model or --models, or SOLOHEAVEN_MODEL."
        )
    if not args.openai_base_url:
        parser.error("--openai-base-url is required")

    return args


def main(argv: list[str] | None = None):
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    args = parse_args(argv)

    from mlx_soloheaven.config import Config
    from mlx_soloheaven.server import run_server

    run_server(Config.from_args(args))
