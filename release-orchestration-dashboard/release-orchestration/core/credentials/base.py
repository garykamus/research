from __future__ import annotations

from abc import ABC, abstractmethod


class CredentialStore(ABC):
    """Abstract interface. Phase 2: backed by Windows DPAPI."""

    @abstractmethod
    def get_credential(self, user_id: str, tool_name: str) -> dict | None: ...

    @abstractmethod
    def set_credential(self, user_id: str, tool_name: str, credential: dict) -> None: ...

    @abstractmethod
    def delete_credential(self, user_id: str, tool_name: str) -> None: ...
