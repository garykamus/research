from __future__ import annotations

from .base import TriggerExecutor
from .browser_executor import BrowserExecutor
from .http_executor import HttpExecutor
from .http_flow_executor import HttpFlowExecutor
from .none_executor import NoneExecutor
from .script_executor import ScriptExecutor
from .webhook_executor import WebhookExecutor


class TriggerExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, TriggerExecutor] = {}
        for executor in [
            NoneExecutor(),
            HttpExecutor(),
            HttpFlowExecutor(),
            WebhookExecutor(),
            ScriptExecutor(),
            BrowserExecutor(),
        ]:
            self._executors[executor.trigger_type] = executor

    def get(self, trigger_type: str) -> TriggerExecutor:
        if trigger_type not in self._executors:
            raise ValueError(f"Unknown trigger type: '{trigger_type}'")
        return self._executors[trigger_type]
