from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerResult:
    status: str
    produced: dict[str, str] = field(default_factory=dict)
    links: list[dict[str, str]] = field(default_factory=list)
    message: str = ""


class TriggerExecutor(ABC):
    trigger_type: str = ""

    @abstractmethod
    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult: ...
