from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import TriggerExecutor, TriggerResult


def _find_scripts_root() -> Path:
    """Find the scripts/ directory relative to the project root."""
    if getattr(sys, "frozen", False):
        # Packaged exe: scripts/ is next to the exe
        return Path(sys.executable).parent / "scripts"
    # Dev mode: scripts/ is at the project root
    return Path(__file__).parent.parent.parent / "scripts"


class ScriptExecutor(TriggerExecutor):
    """
    Runs a script with the bag-in / result-out contract (spec §05.1.3).

    Supported runtimes:
      python  — in-process import + call (same Python process, no subprocess overhead)
      shell   — subprocess via cmd.exe / sh
      groovy  — subprocess
      java    — subprocess (requires java on PATH)

    The script receives context as JSON on stdin and must print a JSON
    result to stdout:
      input:  { lane, bag, creds, market_config }
      output: { status, produced, links, message }

    For python runtime the script is imported as a module and its
    main(context: dict) -> dict function is called directly — faster and
    avoids subprocess serialisation overhead.

    Timeout: enforced on all subprocess runtimes (default 5 minutes).
    Scripts must never log raw credentials (governance — spec §05.1.3).
    """

    trigger_type = "script"
    DEFAULT_TIMEOUT = 300  # 5 minutes

    def execute(self, trigger_config: dict[str, Any], context: dict[str, Any]) -> TriggerResult:
        runtime = trigger_config.get("runtime", "python")
        entry = trigger_config.get("entry", "")
        timeout = int(trigger_config.get("timeout_seconds", self.DEFAULT_TIMEOUT))

        if not entry:
            return TriggerResult(status="FAILED", message="Script trigger has no 'entry' defined")

        script_path = _find_scripts_root() / entry
        if not script_path.exists():
            return TriggerResult(
                status="FAILED",
                message=f"Script not found: {script_path}",
            )

        # Build the bag-in payload — never include raw creds in the message.
        payload = self._build_payload(context)

        if runtime == "python":
            return self._run_python(script_path, payload)
        else:
            return self._run_subprocess(runtime, script_path, payload, timeout)

    # ── Private ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_payload(context: dict[str, Any]) -> dict[str, Any]:
        """Build the standardised input dict. Context keys starting with _ are internal."""
        lane_keys = {"market", "arcad_package", "branch_name", "owner", "jira_id", "confluence_page"}
        lane = {k: context[k] for k in lane_keys if k in context}

        bag_exclude = lane_keys | {"_resolved_url", "_resolved_body", "_auth_type",
                                    "_credential", "_param_map"}
        bag = {k: v for k, v in context.items() if not k.startswith("_") and k not in bag_exclude}

        creds = context.get("_credential") or {}
        market_config = {
            k: v for k, v in context.items()
            if k.startswith("market.") or k.startswith("tool.")
        }

        return {"lane": lane, "bag": bag, "creds": creds, "market_config": market_config}

    @staticmethod
    def _run_python(script_path: Path, payload: dict) -> TriggerResult:
        """Import the script as a module and call main(payload) in-process."""
        try:
            spec = importlib.util.spec_from_file_location("_script_module", script_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if not hasattr(mod, "main"):
                return TriggerResult(
                    status="FAILED",
                    message=f"Script {script_path.name} has no main(context) function",
                )
            result = mod.main(payload)
        except Exception as exc:
            return TriggerResult(status="FAILED", message=f"Script exception: {exc}")

        return ScriptExecutor._parse_result(result)

    @staticmethod
    def _run_subprocess(
        runtime: str, script_path: Path, payload: dict, timeout: int
    ) -> TriggerResult:
        """Run non-Python scripts as a subprocess with JSON over stdin/stdout."""
        cmd_map = {
            "shell": ["cmd.exe", "/c", str(script_path)],
            "groovy": ["groovy", str(script_path)],
            "java": ["java", "-jar", str(script_path)],
        }
        cmd = cmd_map.get(runtime, ["cmd.exe", "/c", str(script_path)])
        stdin_data = json.dumps(payload).encode("utf-8")
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return TriggerResult(
                status="FAILED",
                message=f"Script timed out after {timeout}s",
            )
        except Exception as exc:
            return TriggerResult(status="FAILED", message=f"Subprocess error: {exc}")

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:500]
            return TriggerResult(
                status="FAILED",
                message=f"Script exited {proc.returncode}: {stderr}",
            )

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            return TriggerResult(
                status="FAILED",
                message=f"Script output is not valid JSON: {exc}",
            )

        return ScriptExecutor._parse_result(result)

    @staticmethod
    def _parse_result(result: dict) -> TriggerResult:
        """Convert the bag-out dict to a TriggerResult."""
        if not isinstance(result, dict):
            return TriggerResult(status="FAILED", message="Script returned non-dict result")
        status = result.get("status", "FAILED").upper()
        if status not in ("SUCCESS", "FAILED"):
            status = "FAILED"
        produced = {k: str(v) for k, v in result.get("produced", {}).items()}
        links = result.get("links", [])
        message = result.get("message", "")
        return TriggerResult(status=status, produced=produced, links=links, message=message)
