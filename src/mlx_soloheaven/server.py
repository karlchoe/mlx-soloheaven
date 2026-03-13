"""FastAPI application factory and server entry point."""

from __future__ import annotations

import logging
import os
import socket
import sys
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mlx_soloheaven.config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("soloheaven")


def _build_model_config(base_cfg: Config, model_cfg: Any) -> Config:
    return Config(
        model_path=model_cfg.model_path,
        model_alias=model_cfg.alias,
        openai_base_url=model_cfg.openai_base_url,
        openai_api_key=model_cfg.openai_api_key,
        host=base_cfg.host,
        port=base_cfg.port,
        default_temperature=model_cfg.default_temperature,
        default_top_p=model_cfg.default_top_p,
        default_min_p=model_cfg.default_min_p,
        default_top_k=model_cfg.default_top_k,
        default_repetition_penalty=model_cfg.default_repetition_penalty,
        default_max_tokens=model_cfg.default_max_tokens,
        thinking_budget=model_cfg.thinking_budget,
        enable_thinking=model_cfg.enable_thinking,
        data_dir=base_cfg.data_dir,
        verbose=base_cfg.verbose,
    )


def create_app(cfg: Config) -> FastAPI:
    """Build the FastAPI application with all routes and middleware."""
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, FileResponse

    from mlx_soloheaven.api import admin, chat, compaction, openai_compat, settings
    from mlx_soloheaven.engine.openai_proxy_engine import OpenAIProxyEngine
    from mlx_soloheaven.storage import database as db

    proxy_logger = logging.getLogger("mlx_soloheaven.engine.openai_proxy_engine")
    proxy_logger.setLevel(logging.DEBUG if cfg.verbose else logging.INFO)

    app = FastAPI(
        title="SoloHeaven",
        description="OpenAI-compatible chat server for proxied Qwen3.5-class models",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request, exc):
        body = None
        try:
            body = (await request.body()).decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass
        logger.error(
            "[422] %s %s | errors=%s | body=%s",
            request.method,
            request.url.path,
            exc.errors(),
            body,
        )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    engines: dict[str, Any] = {}
    model_configs = cfg.models or [
        SimpleNamespace(
            model_path=cfg.model_path,
            alias=cfg.model_alias,
            openai_base_url=cfg.openai_base_url,
            openai_api_key=cfg.openai_api_key,
            default_temperature=cfg.default_temperature,
            default_top_p=cfg.default_top_p,
            default_min_p=cfg.default_min_p,
            default_top_k=cfg.default_top_k,
            default_repetition_penalty=cfg.default_repetition_penalty,
            default_max_tokens=cfg.default_max_tokens,
            thinking_budget=cfg.thinking_budget,
            enable_thinking=cfg.enable_thinking,
            model_id=cfg.model_alias or cfg.model_path,
        )
    ]

    for model_cfg in model_configs:
        engine = OpenAIProxyEngine(_build_model_config(cfg, model_cfg))
        engines[model_cfg.model_id] = engine

    default_engine: Any = None

    @app.on_event("startup")
    async def startup():
        nonlocal default_engine

        db.set_db_path(cfg.db_path)
        await db.init_db()
        logger.info("Database initialized: %s", cfg.db_path)

        for model_id, engine in engines.items():
            engine.load_model()
            logger.info("Model ready: %s -> %s", model_id, engine.model_id)

        default_engine = next(iter(engines.values()))
        openai_compat.set_engines(engines, default_engine)
        chat.set_engines(engines, default_engine)
        admin.set_engines(engines, default_engine)
        compaction.set_engine(default_engine)
        admin.install_log_handler()

        logger.info("Server ready on http://%s:%s", cfg.host, cfg.port)
        logger.info("  Web UI:     http://%s:%s/", cfg.host, cfg.port)
        logger.info("  Admin:      http://%s:%s/admin", cfg.host, cfg.port)
        logger.info("  OpenAI API: http://%s:%s/v1/chat/completions", cfg.host, cfg.port)
        logger.info("  Models:     %s", list(engines.keys()))

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "backend": "openai-compatible",
            "models": {
                model_id: {
                    "model_id": engine.model_id,
                    "sessions": engine.session_stats(),
                }
                for model_id, engine in engines.items()
            },
        }

    app.include_router(openai_compat.router)
    app.include_router(chat.router)
    app.include_router(settings.router)
    app.include_router(compaction.router)
    app.include_router(admin.router)

    web_dir = os.path.join(os.path.dirname(__file__), "web")
    if os.path.isdir(web_dir):

        @app.get("/admin")
        async def admin_page():
            return FileResponse(os.path.join(web_dir, "admin.html"))

        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")

    return app


def _check_port(host: str, port: int):
    """Exit early if port is already in use."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host if host != "0.0.0.0" else "127.0.0.1", port))
    except OSError:
        logger.error("Port %s is already in use. Stop the existing server first.", port)
        sys.exit(1)
    finally:
        sock.close()


def run_server(cfg: Config):
    """Start the uvicorn server."""
    import uvicorn

    _check_port(cfg.host, cfg.port)
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", loop="asyncio")
