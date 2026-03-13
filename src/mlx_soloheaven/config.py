"""Configuration dataclass populated from CLI args or environment."""

from argparse import Namespace
from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """Per-model configuration."""

    model_path: str
    alias: str = ""
    openai_base_url: str = ""
    openai_api_key: str = "EMPTY"
    default_temperature: float = 0.6
    default_top_p: float = 1.0
    default_min_p: float = 0.0
    default_top_k: int = 0
    default_repetition_penalty: float = 1.0
    default_max_tokens: int = 32768
    thinking_budget: int = 8192
    enable_thinking: bool = True

    @property
    def model_id(self) -> str:
        return self.alias or self.model_path


@dataclass
class Config:
    models: list[ModelConfig] = field(default_factory=list)
    model_path: str = ""
    model_alias: str = ""
    openai_base_url: str = ""
    openai_api_key: str = "EMPTY"
    host: str = "0.0.0.0"
    port: int = 8000
    default_temperature: float = 0.6
    default_top_p: float = 1.0
    default_min_p: float = 0.0
    default_top_k: int = 0
    default_repetition_penalty: float = 1.0
    default_max_tokens: int = 32768
    thinking_budget: int = 8192
    enable_thinking: bool = True
    data_dir: str = "./data"
    verbose: bool = False

    @property
    def cache_dir(self) -> str:
        return ""

    @property
    def db_path(self) -> str:
        return f"{self.data_dir}/soloheaven.db"

    @classmethod
    def from_args(cls, args: Namespace) -> "Config":
        models: list[ModelConfig] = []

        def _build_model(spec: str) -> ModelConfig:
            alias = ""
            enable_thinking = not args.no_thinking
            normalized = spec
            if ":no_think_tag" in normalized:
                normalized = normalized.replace(":no_think_tag", "")
                enable_thinking = False
            if "=" in normalized:
                alias, model_id = normalized.split("=", 1)
            else:
                model_id = normalized
            return ModelConfig(
                model_path=model_id.strip(),
                alias=alias.strip(),
                openai_base_url=args.openai_base_url,
                openai_api_key=args.openai_api_key,
                default_temperature=args.temperature,
                default_top_p=args.top_p,
                default_min_p=args.min_p,
                default_top_k=args.top_k,
                default_repetition_penalty=args.repetition_penalty,
                default_max_tokens=args.max_tokens,
                thinking_budget=args.thinking_budget,
                enable_thinking=enable_thinking,
            )

        if args.models:
            models = [_build_model(spec) for spec in args.models]
        elif args.model:
            models = [_build_model(args.model)]

        return cls(
            models=models,
            model_path=args.model or (models[0].model_path if models else ""),
            model_alias=models[0].alias if models else "",
            openai_base_url=args.openai_base_url,
            openai_api_key=args.openai_api_key,
            host=args.host,
            port=args.port,
            default_temperature=args.temperature,
            default_top_p=args.top_p,
            default_min_p=args.min_p,
            default_top_k=args.top_k,
            default_repetition_penalty=args.repetition_penalty,
            default_max_tokens=args.max_tokens,
            thinking_budget=args.thinking_budget,
            enable_thinking=not args.no_thinking,
            data_dir=args.data_dir,
            verbose=args.verbose,
        )
