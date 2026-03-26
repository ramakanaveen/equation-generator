"""
Configuration for equation-generator.

Reads config.yaml first, then overrides with EQ_GEN_* environment variables.
Access via the module-level singleton: from config import cfg
"""

import os
from dataclasses import dataclass, field

import yaml


def _env(key: str, default: str = "") -> str:
    """Read EQ_GEN_{KEY} env var, falling back to default."""
    return os.getenv(f"EQ_GEN_{key.upper()}", default)


def _load_yaml() -> dict:
    yaml_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if not os.path.exists(yaml_path):
        return {}
    with open(yaml_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    # Provider
    provider: str = "anthropic"

    # Vertex
    vertex_project_id: str = ""
    vertex_region: str = "us-east5"
    vertex_base_url: str = ""

    # Model
    model_name: str = "claude-sonnet-4-20250514"
    model_vertex_name: str = "claude-sonnet-4@20250514"
    max_tokens: int = 16384

    # Generation
    target_count: int = 20
    eq_batch_size: int = 5
    code_batch_size: int = 2
    max_continuations: int = 3

    # Server
    port: int = 8000

    # CORS
    cors_origins: list = field(default_factory=lambda: ["*"])


def _build() -> Config:
    y = _load_yaml()

    vertex = y.get("vertex", {})
    model  = y.get("model", {})
    gen    = y.get("generation", {})

    return Config(
        provider=_env("PROVIDER", y.get("provider", "anthropic")),

        vertex_project_id=_env("VERTEX_PROJECT_ID", vertex.get("project_id", "")),
        vertex_region=_env("VERTEX_REGION", vertex.get("region", "us-east5")),
        vertex_base_url=_env("VERTEX_BASE_URL", vertex.get("base_url", "")),

        model_name=_env("MODEL_NAME", model.get("name", "claude-sonnet-4-20250514")),
        model_vertex_name=_env("MODEL_VERTEX_NAME", model.get("vertex_name", "claude-sonnet-4@20250514")),
        max_tokens=int(_env("MAX_TOKENS", str(model.get("max_tokens", 16384)))),

        target_count=int(_env("TARGET_COUNT", str(gen.get("target_count", 20)))),
        eq_batch_size=int(_env("EQ_BATCH_SIZE", str(gen.get("eq_batch_size", 5)))),
        code_batch_size=int(_env("CODE_BATCH_SIZE", str(gen.get("code_batch_size", 2)))),
        max_continuations=int(_env("MAX_CONTINUATIONS", str(gen.get("max_continuations", 3)))),

        port=int(_env("PORT", str(y.get("port", 8000)))),
        cors_origins=_build_cors_origins(y),
    )


def _build_cors_origins(y: dict) -> list[str]:
    env_val = os.getenv("EQ_GEN_CORS_ORIGINS", "")
    if env_val:
        return [o.strip() for o in env_val.split(",") if o.strip()]
    return y.get("cors_origins", ["*"])


cfg = _build()
