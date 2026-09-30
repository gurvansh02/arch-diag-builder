"""
Settings an admin can change from the UI, persisted to a small JSON file.

`.env` stays the source of defaults; this file only holds the handful of
values that have to be changeable without editing files and restarting -
offline mode and which locally downloaded model to use. A value that has
never been set falls back to its `.env` default, so deleting the file
returns the app to its configured behaviour.
"""

import json
import logging
import threading
from typing import Any, Dict

from config.settings import (
    OFFLINE_MODE,
    OLLAMA_LLM_MODEL,
    OLLAMA_VISION_MODEL,
    RUNTIME_CONFIG_FILE,
)

logger = logging.getLogger(__name__)


class RuntimeConfig:
    """JSON-backed key/value store for admin-editable settings."""

    def __init__(self, path=RUNTIME_CONFIG_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = self._read()

    # ==================== Defaults ====================

    @property
    def defaults(self) -> Dict[str, Any]:
        """Fall-back values, taken from .env at import time."""
        return {
            "offline_mode": OFFLINE_MODE,
            "ollama_llm_model": OLLAMA_LLM_MODEL,
            "ollama_vision_model": OLLAMA_VISION_MODEL,
        }

    # ==================== Access ====================

    def get(self, key: str) -> Any:
        """Current value for one setting."""
        return self.all().get(key)

    def all(self) -> Dict[str, Any]:
        """Every setting, with defaults filled in."""
        values = dict(self.defaults)
        values.update(self._cache)
        return values

    def set(self, **values: Any) -> None:
        """Update one or more settings and persist them."""
        with self._lock:
            self._cache.update(values)
            self._write(self._cache)
        logger.info("Runtime config updated: %s", ", ".join(values))

    def reset(self) -> None:
        """Drop every override and go back to the .env defaults."""
        with self._lock:
            self._cache = {}
            self._write({})
        logger.info("Runtime config reset to .env defaults")

    # ==================== Persistence ====================

    def _read(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            # A corrupt settings file must not stop the app from starting.
            logger.warning("Could not read %s (%s) - using defaults", self.path, e)
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Could not save runtime config: %s", e)


runtime_config = RuntimeConfig()
