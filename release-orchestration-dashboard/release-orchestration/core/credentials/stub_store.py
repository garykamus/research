from __future__ import annotations

from .base import CredentialStore


class StubCredentialStore(CredentialStore):
    """Phase 1: returns None for all lookups. Phase 2: replace with DPAPICredentialStore."""

    def get_credential(self, user_id: str, tool_name: str) -> dict | None:
        return None

    def set_credential(self, user_id: str, tool_name: str, credential: dict) -> None:
        pass

    def delete_credential(self, user_id: str, tool_name: str) -> None:
        pass


class InMemoryCredentialStore(CredentialStore):
    """
    In-memory credential store for tests and dev scenarios.
    Stores credentials in plaintext in a dict — never use in production.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict] = {}

    def get_credential(self, user_id: str, tool_name: str) -> dict | None:
        return self._store.get((user_id, tool_name))

    def set_credential(self, user_id: str, tool_name: str, credential: dict) -> None:
        self._store[(user_id, tool_name)] = dict(credential)

    def delete_credential(self, user_id: str, tool_name: str) -> None:
        self._store.pop((user_id, tool_name), None)

    def list_configured_tools(self, user_id: str) -> list[str]:
        return [tool for (uid, tool) in self._store if uid == user_id]
