from __future__ import annotations

import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml


class ConfigStore(ABC):
    """Abstract interface — the engine never touches file paths directly."""

    @abstractmethod
    def get_step_definition(self, step_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_template(self, template_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_market_binding(self, market: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_tools(self) -> dict[str, Any]: ...

    @abstractmethod
    def get_lane_actions(self) -> dict[str, Any]: ...

    @abstractmethod
    def list_markets(self) -> list[str]: ...

    @abstractmethod
    def list_templates(self) -> list[str]: ...


class FileConfigLoader(ConfigStore):
    """
    Loads config from the config/ directory.

    Config root resolution order:
    1. RELEASE_ORCH_CONFIG_DIR env var
    2. sys._MEIPASS/config  (frozen PyInstaller exe)
    3. <this file>/../../config  (dev mode)
    """

    def __init__(self, config_root: str | None = None) -> None:
        self._root = Path(config_root or self._find_config_root())
        self._steps: dict[str, Any] = {}
        self._templates: dict[str, Any] = {}
        self._markets: dict[str, Any] = {}
        self._tools: dict[str, Any] = {}
        self._lane_actions: dict[str, Any] = {}
        self._load_all()

    @staticmethod
    def _find_config_root() -> str:
        env = os.environ.get("RELEASE_ORCH_CONFIG_DIR")
        if env:
            return env
        if getattr(sys, "frozen", False):
            return os.path.join(sys._MEIPASS, "config")
        return str(Path(__file__).parent.parent.parent / "config")

    def _load_all(self) -> None:
        self._steps = self._load_dir(self._root / "steps", "steps")
        self._templates = self._load_dir(self._root / "templates", "templates")
        self._markets = self._load_markets(self._root / "markets")
        self._tools = self._load_file(self._root / "tools" / "tools.yaml").get("tools", {})
        actions_path = self._root / "lane_actions.yaml"
        self._lane_actions = self._load_file(actions_path).get("lane_actions", {})

    def _load_dir(self, directory: Path, key: str) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if not directory.exists():
            return merged
        for path in sorted(directory.glob("*.yaml")):
            data = self._load_file(path)
            merged.update(data.get(key, {}))
        return merged

    def _load_markets(self, directory: Path) -> dict[str, Any]:
        markets: dict[str, Any] = {}
        if not directory.exists():
            return markets
        for path in sorted(directory.glob("*.yaml")):
            data = self._load_file(path)
            market_id = data.get("market")
            if market_id:
                markets[market_id] = data
        return markets

    @staticmethod
    def _load_file(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_step_definition(self, step_id: str) -> dict[str, Any]:
        if step_id not in self._steps:
            raise KeyError(f"Step '{step_id}' not found in step library")
        return dict(self._steps[step_id])

    def get_template(self, template_id: str) -> dict[str, Any]:
        if template_id not in self._templates:
            raise KeyError(f"Template '{template_id}' not found")
        return dict(self._templates[template_id])

    def get_market_binding(self, market: str) -> dict[str, Any]:
        if market not in self._markets:
            raise KeyError(f"Market '{market}' not found in config")
        return dict(self._markets[market])

    def get_tools(self) -> dict[str, Any]:
        return dict(self._tools)

    def get_lane_actions(self) -> dict[str, Any]:
        return dict(self._lane_actions)

    def list_markets(self) -> list[str]:
        return sorted(self._markets.keys())

    def list_templates(self) -> list[str]:
        return sorted(self._templates.keys())
