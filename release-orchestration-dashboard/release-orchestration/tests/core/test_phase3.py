"""
Phase 3 tests: ServiceNow/Confluence/Jira clients, script executor,
custom views (import-level), post-actions, config view assignments.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.config.loader import FileConfigLoader
from core.credentials.stub_store import StubCredentialStore
from core.persistence.context import PersistenceContext
from core.service import ReleaseService


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_service() -> tuple[ReleaseService, str]:
    tmp = tempfile.mktemp(suffix=".db")
    ctx = PersistenceContext(tmp)
    config = FileConfigLoader()
    svc = ReleaseService(ctx, config, StubCredentialStore())
    user = ctx.users.get_or_create_default_user("tester", "Tester")
    return svc, user.id


def _create_hk_lane(svc, uid):
    return svc.create_lane(
        "HK", "pkg-100", uid, "PROJ-1", "https://conf/1", uid,
        skip_steps=["create_arcad_package"],
    )


# ── ServiceNow client ─────────────────────────────────────────────────────────

class TestServiceNowClient(unittest.TestCase):
    def _make_client(self, token="tok"):
        from core.integrations.servicenow import ServiceNowClient
        return ServiceNowClient("https://snow.placeholder/api/now", token)

    def test_create_change_request_success(self):
        client = self._make_client()
        mock_resp = json.dumps({
            "result": {
                "number": "CHG0001234",
                "sys_id": "abc123",
                "sys_url": "https://snow.placeholder/now/change/CHG0001234",
            }
        }).encode()
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp_obj = MagicMock()
            mock_resp_obj.status = 201
            mock_resp_obj.read.return_value = mock_resp
            mock_resp_obj.__enter__ = lambda s: s
            mock_resp_obj.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp_obj
            result = client.create_change_request({"short_description": "Test"})
        self.assertEqual(result["cr_no"], "CHG0001234")
        self.assertIn("sys_id", result)

    def test_build_deep_link(self):
        from core.integrations.servicenow import ServiceNowClient
        url = ServiceNowClient.build_deep_link(
            "https://snow.placeholder",
            {"short_description": "Release pkg-001", "assignment_group": "team-hk"}
        )
        self.assertIn("now/change/create", url)
        self.assertIn("short_description", url)

    def test_build_cr_deep_link(self):
        from core.integrations.servicenow import ServiceNowClient
        url = ServiceNowClient.build_cr_deep_link("https://snow.placeholder", "CHG0001234")
        self.assertIn("CHG0001234", url)

    def test_get_change_request_http_error(self):
        import urllib.error
        client = self._make_client()
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="", code=403, msg="Forbidden", hdrs=None, fp=None
            )
            with self.assertRaises(RuntimeError) as ctx:
                client.get_change_request("CHG0001234")
            self.assertIn("403", str(ctx.exception))


# ── Confluence client ─────────────────────────────────────────────────────────

class TestConfluenceClient(unittest.TestCase):
    def _make_client(self):
        from core.integrations.confluence import ConfluenceClient
        return ConfluenceClient("https://confluence.placeholder/rest/api", token="tok")

    def test_update_page_sends_put(self):
        client = self._make_client()
        mock_resp = json.dumps({"id": "12345", "title": "Release page"}).encode()
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp_obj = MagicMock()
            mock_resp_obj.status = 200
            mock_resp_obj.read.return_value = mock_resp
            mock_resp_obj.__enter__ = lambda s: s
            mock_resp_obj.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp_obj
            result = client.update_page("12345", "Release page", "<p>content</p>", 5)
        self.assertEqual(result["id"], "12345")

    def test_build_release_table_html_contains_key_fields(self):
        from core.integrations.confluence import ConfluenceClient
        client = ConfluenceClient("https://confluence.placeholder/rest/api")
        html = client.build_release_table_html(
            {"arcad_package": "pkg-001", "market": "HK", "jira_id": "PROJ-1"},
            {"cr_no": "CR001", "build_url": "https://jenkins/build/1"}
        )
        self.assertIn("pkg-001", html)
        self.assertIn("CR001", html)
        self.assertIn("<table>", html)

    def test_build_deep_link(self):
        from core.integrations.confluence import ConfluenceClient
        url = ConfluenceClient.build_deep_link("https://confluence.placeholder", "99999")
        self.assertIn("99999", url)
        self.assertIn("confluence", url)


# ── Jira client ───────────────────────────────────────────────────────────────

class TestJiraClient(unittest.TestCase):
    def _make_client(self):
        from core.integrations.jira import JiraClient
        return JiraClient("https://jira.placeholder/rest/api/2", token="tok")

    def test_get_transitions(self):
        client = self._make_client()
        mock_resp = json.dumps({
            "transitions": [
                {"id": "31", "name": "In Progress"},
                {"id": "41", "name": "Done"},
            ]
        }).encode()
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp_obj = MagicMock()
            mock_resp_obj.status = 200
            mock_resp_obj.read.return_value = mock_resp
            mock_resp_obj.__enter__ = lambda s: s
            mock_resp_obj.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp_obj
            transitions = client.get_transitions("PROJ-1")
        self.assertEqual(len(transitions), 2)
        self.assertEqual(transitions[0]["name"], "In Progress")

    def test_transition_by_name_not_found(self):
        client = self._make_client()
        mock_resp = json.dumps({"transitions": [{"id": "31", "name": "In Progress"}]}).encode()
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp_obj = MagicMock()
            mock_resp_obj.status = 200
            mock_resp_obj.read.return_value = mock_resp
            mock_resp_obj.__enter__ = lambda s: s
            mock_resp_obj.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp_obj
            result = client.transition_by_name("PROJ-1", "Nonexistent")
        self.assertFalse(result)


# ── Script executor ───────────────────────────────────────────────────────────

class TestScriptExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def _write_script(self, name: str, content: str) -> None:
        path = os.path.join(self.tmp_dir, name)
        with open(path, "w") as f:
            f.write(content)

    def test_python_script_success(self):
        from core.triggers.script_executor import ScriptExecutor, _find_scripts_root
        self._write_script("test_ok.py", """
def main(context):
    return {
        "status": "SUCCESS",
        "produced": {"cr_no": "CR001"},
        "links": [{"label": "Test", "url": "https://example.com"}],
        "message": "done",
    }
""")
        executor = ScriptExecutor()
        import pathlib
        with patch("core.triggers.script_executor._find_scripts_root",
                   return_value=pathlib.Path(self.tmp_dir)):
            result = executor.execute(
                {"runtime": "python", "entry": "test_ok.py"},
                {"market": "HK", "arcad_package": "pkg-001"},
            )
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(result.produced.get("cr_no"), "CR001")
        self.assertEqual(len(result.links), 1)

    def test_python_script_failure(self):
        from core.triggers.script_executor import ScriptExecutor
        self._write_script("test_fail.py", """
def main(context):
    return {"status": "FAILED", "message": "something went wrong"}
""")
        executor = ScriptExecutor()
        import pathlib
        with patch("core.triggers.script_executor._find_scripts_root",
                   return_value=pathlib.Path(self.tmp_dir)):
            result = executor.execute(
                {"runtime": "python", "entry": "test_fail.py"},
                {},
            )
        self.assertEqual(result.status, "FAILED")

    def test_script_not_found(self):
        from core.triggers.script_executor import ScriptExecutor
        import pathlib
        executor = ScriptExecutor()
        with patch("core.triggers.script_executor._find_scripts_root",
                   return_value=pathlib.Path(self.tmp_dir)):
            result = executor.execute(
                {"runtime": "python", "entry": "no_such_script.py"},
                {},
            )
        self.assertEqual(result.status, "FAILED")
        self.assertIn("not found", result.message)

    def test_python_script_exception(self):
        from core.triggers.script_executor import ScriptExecutor
        self._write_script("test_exc.py", """
def main(context):
    raise ValueError("deliberate error")
""")
        executor = ScriptExecutor()
        import pathlib
        with patch("core.triggers.script_executor._find_scripts_root",
                   return_value=pathlib.Path(self.tmp_dir)):
            result = executor.execute(
                {"runtime": "python", "entry": "test_exc.py"},
                {},
            )
        self.assertEqual(result.status, "FAILED")
        self.assertIn("deliberate error", result.message)

    def test_script_missing_entry(self):
        from core.triggers.script_executor import ScriptExecutor
        executor = ScriptExecutor()
        result = executor.execute({"runtime": "python"}, {})
        self.assertEqual(result.status, "FAILED")
        self.assertIn("no 'entry'", result.message)


# ── Config: custom views assigned ────────────────────────────────────────────

class TestCustomViewsInConfig(unittest.TestCase):
    def setUp(self):
        self.loader = FileConfigLoader()

    def test_create_cr_uses_cr_creation_view(self):
        step = self.loader.get_step_definition("create_cr")
        self.assertEqual(step["view"], "cr_creation")

    def test_update_evidence_uses_evidence_update_view(self):
        step = self.loader.get_step_definition("update_evidence")
        self.assertEqual(step["view"], "evidence_update")

    def test_update_confluence_uses_confluence_release_view(self):
        step = self.loader.get_step_definition("update_confluence_release")
        self.assertEqual(step["view"], "confluence_release")

    def test_submit_cr_has_post_action(self):
        step = self.loader.get_step_definition("submit_cr")
        self.assertTrue(len(step.get("post_actions", [])) > 0)
        post_action = step["post_actions"][0]
        self.assertEqual(post_action.get("when"), "DONE")

    def test_update_jira_status_has_http_trigger(self):
        step = self.loader.get_step_definition("update_jira_status")
        self.assertEqual(step["trigger"]["type"], "http")

    def test_all_markets_still_validate_after_config_changes(self):
        from core.config.resolver import LaneResolver
        resolver = LaneResolver(self.loader)
        results = resolver.validate_all_markets()
        broken = {m: e for m, e in results.items() if e}
        self.assertEqual(broken, {}, f"Market config errors: {broken}")


# ── Post-actions ──────────────────────────────────────────────────────────────

class TestPostActions(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()
        self.lane = _create_hk_lane(self.svc, self.uid)

    def test_post_action_fires_and_is_audited_on_success(self):
        # Advance all steps up to submit_cr and fire it (which has a post-action).
        steps_values = [
            ("create_pr", {"pr_url": "https://github.com/pr/1"}),
            ("release_build", {"build_url": "https://j/build/1", "build_result": "SUCCESS"}),
            ("sast_scan", {"sast_url": "https://sast/1", "cyber_url": "https://cyber/1"}),
            ("create_cr", {"cr_no": "CR001", "cr_url": "https://snow/CR001"}),
            ("arcad_lock", {}),
            ("g3_package", {"g3_url": "https://j/g3/1"}),
        ]
        mock_success = MagicMock()
        mock_success.status = "SUCCESS"
        mock_success.produced = {}
        mock_success.links = []
        with patch("core.triggers.http_executor.HttpExecutor.execute", return_value=mock_success), \
             patch("core.triggers.http_flow_executor.HttpFlowExecutor.execute", return_value=mock_success):
            for step_id, vals in steps_values:
                self.svc.advance_step(self.lane.id, step_id, self.uid, recorded_values=vals)

        # fire submit_cr — it has a post-action (Jira transition)
        with patch("core.triggers.http_executor.HttpExecutor.execute", return_value=mock_success):
            self.svc.fire_step(self.lane.id, "submit_cr", self.uid)

        audit = self.svc.get_audit_log(self.lane.id)
        events = [e.event_type for e in audit]
        self.assertIn("POST_ACTION_FIRED", events)

    def test_post_action_failure_does_not_block_lane(self):
        """A failing post-action surfaces in audit but does not set lane BLOCKED."""
        steps_values = [
            ("create_pr", {"pr_url": "https://github.com/pr/1"}),
            ("release_build", {"build_url": "https://j/build/1", "build_result": "SUCCESS"}),
            ("sast_scan", {"sast_url": "https://sast/1", "cyber_url": "https://cyber/1"}),
            ("create_cr", {"cr_no": "CR001", "cr_url": "https://snow/CR001"}),
            ("arcad_lock", {}),
            ("g3_package", {"g3_url": "https://j/g3/1"}),
        ]
        mock_success = MagicMock()
        mock_success.status = "SUCCESS"
        mock_success.produced = {}
        mock_success.links = []
        with patch("core.triggers.http_executor.HttpExecutor.execute", return_value=mock_success), \
             patch("core.triggers.http_flow_executor.HttpFlowExecutor.execute", return_value=mock_success):
            for step_id, vals in steps_values:
                self.svc.advance_step(self.lane.id, step_id, self.uid, recorded_values=vals)

        # Simulate post-action Jira call failing
        mock_fail = MagicMock()
        mock_fail.status = "SUCCESS"   # main trigger succeeds
        mock_fail.produced = {}
        mock_fail.links = []

        call_count = [0]
        def side_effect(trigger_cfg, context):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_fail  # main trigger OK
            raise RuntimeError("Jira 503")  # post-action fails

        with patch("core.triggers.http_executor.HttpExecutor.execute", side_effect=side_effect):
            step = self.svc.fire_step(self.lane.id, "submit_cr", self.uid)

        # Step itself succeeded
        self.assertEqual(step.status, "DONE")
        # Lane is not blocked
        lane = self.svc.get_lane(self.lane.id)
        self.assertNotEqual(lane.status, "BLOCKED")
        # Post-action failure is in audit
        audit = self.svc.get_audit_log(self.lane.id)
        pa_events = [e for e in audit if e.event_type == "POST_ACTION_FIRED"]
        self.assertTrue(len(pa_events) > 0)


# ── Custom view registry ──────────────────────────────────────────────────────

class TestCustomViewRegistry(unittest.TestCase):
    def test_auto_register_includes_custom_views(self):
        # Import PySide6 is needed; skip if not available.
        try:
            import PySide6
        except ImportError:
            self.skipTest("PySide6 not installed")

        # Need a QApplication for Qt widget imports
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        from ui.stepviews.registry import _auto_register, get_view_class, _REGISTRY
        _auto_register()
        self.assertIn("cr_creation", _REGISTRY)
        self.assertIn("evidence_update", _REGISTRY)
        self.assertIn("confluence_release", _REGISTRY)

    def test_get_view_falls_back_to_generic(self):
        try:
            import PySide6
        except ImportError:
            self.skipTest("PySide6 not installed")
        import sys
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        from ui.stepviews.registry import get_view_class
        from ui.stepviews.generic_view import GenericStepView
        cls = get_view_class("nonexistent_view")
        self.assertIs(cls, GenericStepView)


if __name__ == "__main__":
    unittest.main()
