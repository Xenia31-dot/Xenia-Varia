"""Settings, read from environment variables. No secrets live in code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    data_dir: Path = Path("data")
    embedder: str = "default"  # "default" (local MiniLM) or "hashing" (offline, for tests)
    top_k: int = 6
    library_k: int = 3
    library_min_score: float = 0.75
    chunk_size: int = 1200
    chunk_overlap: int = 200
    batch_size: int = 5
    max_retries: int = 4
    use_fallback: bool = True


def get_settings() -> Settings:
    return Settings(
        model=os.environ.get("RFP_MODEL", Settings.model),
        effort=os.environ.get("RFP_EFFORT", Settings.effort),
        data_dir=Path(os.environ.get("RFP_DATA_DIR", "data")),
        embedder=os.environ.get("RFP_EMBEDDER", Settings.embedder),
        top_k=_env_int("RFP_TOP_K", Settings.top_k),
        batch_size=_env_int("RFP_BATCH_SIZE", Settings.batch_size),
        max_retries=_env_int("RFP_MAX_RETRIES", Settings.max_retries),
        use_fallback=_env_bool("RFP_USE_FALLBACK", Settings.use_fallback),
    )


def api_key_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
