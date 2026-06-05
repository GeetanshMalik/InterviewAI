from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from config import settings


logger = logging.getLogger("interviewos.persistence")


def postgres_enabled() -> bool:
    return bool(
        (settings.postgres_persistence_enabled or settings.app_env == "production")
        and sync_database_url()
    )


def postgres_strict() -> bool:
    return bool(settings.postgres_persistence_strict or settings.app_env == "production")


def sync_database_url() -> str | None:
    if settings.database_url_sync:
        return settings.database_url_sync
    if settings.database_url:
        return settings.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return None


def migration_dir() -> Path:
    configured = Path(settings.migrations_dir)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parents[2] / configured


def valid_uuid(value: Any) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        logger.warning("Skipping non-UUID persistence id: %s", value)
        return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_bool(value: Any) -> bool:
    return bool(value)


def iso_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}
