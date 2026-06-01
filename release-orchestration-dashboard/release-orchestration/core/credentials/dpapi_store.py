from __future__ import annotations

import base64
import json
import logging

from .base import CredentialStore

logger = logging.getLogger(__name__)

# DPAPI is Windows-only. Import lazily so tests on non-Windows don't break.
def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt plaintext string with Windows DPAPI. Returns base64-encoded blob."""
    import ctypes
    import ctypes.wintypes

    data = plaintext.encode("utf-8")
    buf = ctypes.create_string_buffer(data)
    blob_in = _CRYPTOAPI_BLOB(len(data), buf)
    blob_out = _CRYPTOAPI_BLOB()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None, None, None, None,
        0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(f"CryptProtectData failed: {ctypes.GetLastError()}")

    encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _dpapi_decrypt(blob_b64: str) -> str:
    """Decrypt a DPAPI-encrypted base64 blob back to plaintext."""
    import ctypes

    data = base64.b64decode(blob_b64)
    buf = ctypes.create_string_buffer(data)
    blob_in = _CRYPTOAPI_BLOB(len(data), buf)
    blob_out = _CRYPTOAPI_BLOB()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None, None, None, None,
        0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise OSError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")

    decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return decrypted.decode("utf-8")


import ctypes
import ctypes.wintypes

class _CRYPTOAPI_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


class DPAPICredentialStore(CredentialStore):
    """
    Windows DPAPI-backed credential store.
    Credentials are encrypted with DPAPI (user-scope) before being stored
    in the SQLite credentials table. Never stores plaintext.

    Auth types supported (matching tools.yaml):
      token   → {"token": "<value>"}
      basic   → {"username": "<u>", "password": "<p>"}
      form_login → {"username": "<u>", "password": "<p>"}
    """

    def __init__(self, credential_dal) -> None:
        self._dal = credential_dal

    def get_credential(self, user_id: str, tool_name: str) -> dict | None:
        blob = self._dal.get(user_id, tool_name)
        if not blob:
            return None
        try:
            plaintext = _dpapi_decrypt(blob)
            return json.loads(plaintext)
        except Exception:
            logger.exception("Failed to decrypt credential for user=%s tool=%s", user_id, tool_name)
            return None

    def set_credential(self, user_id: str, tool_name: str, credential: dict) -> None:
        plaintext = json.dumps(credential)
        blob = _dpapi_encrypt(plaintext)
        self._dal.upsert(user_id, tool_name, blob)

    def delete_credential(self, user_id: str, tool_name: str) -> None:
        self._dal.delete(user_id, tool_name)

    def list_configured_tools(self, user_id: str) -> list[str]:
        return self._dal.list_tools(user_id)
