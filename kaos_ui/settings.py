"""Settings for kaos-ui.

Resolution order matches the top-level ``CLAUDE.md`` configuration
hierarchy. ``KaosUISettings`` is intentionally narrow today — it only
pins toolchain versions and an optional template-directory override —
but follows the standard pattern so future fields slot in cleanly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kaos_core.config import ModuleSettings
from pydantic import model_validator
from pydantic_settings import SettingsConfigDict


class KaosUISettings(ModuleSettings):
    """Configuration for the kaos-ui scaffolder.

    Environment prefix: ``KAOS_UI_``. Resolution order is the standard
    KAOS hierarchy — explicit overrides → ``KaosContext._config`` →
    prefixed env vars → legacy env vars → ``.env`` → field defaults.
    """

    python_version: str = "3.14"
    node_version: str = "24"
    templates_dir: Path | None = None
    """Override the bundled templates directory. ``None`` means use the
    templates shipped alongside this package."""

    model_config = SettingsConfigDict(
        env_prefix="KAOS_UI_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def _legacy_env_fallback(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("python_version"):
            legacy = os.environ.get("KAOS_PYTHON_VERSION")
            if legacy:
                values["python_version"] = legacy
        if not values.get("node_version"):
            legacy = os.environ.get("KAOS_NODE_VERSION")
            if legacy:
                values["node_version"] = legacy
        return values
