"""Corp-Collab: centralized configuration with YAML file backing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_BASE_PATH = Path.home() / ".claude-code" / "collab"
CONFIG_FILE = "config.yaml"

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "max_delegation_depth": 10,
    "max_idle_headcount": 5,
    "auto_register_managers": True,
}


# ── Config ────────────────────────────────────────────────────────────────────


class Config:
    """Singleton-ish config reader with YAML file backing.

    Reads from ``<base_path>/config.yaml``. Missing keys fall back to DEFAULTS.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or DEFAULT_BASE_PATH
        self.config_path = self.base_path / CONFIG_FILE
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                data = yaml.safe_load(f)
            self._data = data if isinstance(data, dict) else {}
        else:
            self._data = {}

    def _save(self) -> None:
        self.base_path.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value. Falls back to DEFAULTS, then to *default*."""
        if key in self._data:
            return self._data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return default

    def set(self, key: str, value: Any, persist: bool = True) -> None:
        """Set a config value. Persists to disk by default."""
        self._data[key] = value
        if persist:
            self._save()

    @property
    def max_delegation_depth(self) -> int:
        val = self.get("max_delegation_depth")
        return min(int(val), 10)  # hard cap at 10

    @max_delegation_depth.setter
    def max_delegation_depth(self, value: int) -> None:
        self.set("max_delegation_depth", min(int(value), 10))

    @property
    def max_idle_headcount(self) -> int:
        return int(self.get("max_idle_headcount"))

    @property
    def auto_register_managers(self) -> bool:
        return bool(self.get("auto_register_managers"))

    def reload(self) -> None:
        """Re-read from disk."""
        self._load()

    def to_dict(self) -> dict[str, Any]:
        """Return merged config (file values + defaults for missing keys)."""
        merged = dict(DEFAULTS)
        merged.update(self._data)
        return merged


def get_config(base_path: Path | None = None) -> Config:
    """Convenience factory."""
    return Config(base_path=base_path)
