from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.config.loader import FileConfigLoader


class TestFileConfigLoader(unittest.TestCase):
    def setUp(self):
        self.loader = FileConfigLoader()

    def test_lists_all_four_placeholder_markets(self):
        markets = self.loader.list_markets()
        for m in ("HK", "SG", "ID", "TH"):
            self.assertIn(m, markets)

    def test_get_known_step(self):
        step = self.loader.get_step_definition("create_pr")
        self.assertEqual(step["label"], "Create PR on GitHub")
        self.assertEqual(step["mode"], "HYBRID")

    def test_get_compliance_step(self):
        step = self.loader.get_step_definition("regional_compliance")
        self.assertIn("produces", step)

    def test_get_external_hold_step(self):
        step = self.loader.get_step_definition("external_dev_work")
        self.assertEqual(step["kind"], "external_hold")
        self.assertIn("resume", step)

    def test_get_unknown_step_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.loader.get_step_definition("does_not_exist")

    def test_get_market_binding_hk(self):
        binding = self.loader.get_market_binding("HK")
        self.assertEqual(binding["use"], "backbone")
        self.assertIn("urls", binding)

    def test_get_market_binding_id_has_add_and_override(self):
        binding = self.loader.get_market_binding("ID")
        self.assertEqual(binding["use"], "regulated_flow")
        self.assertTrue(len(binding.get("add", [])) > 0)
        self.assertIn("create_cr", binding.get("override", {}))

    def test_get_unknown_market_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.loader.get_market_binding("XX")

    def test_get_templates(self):
        templates = self.loader.list_templates()
        for t in ("backbone", "regulated_flow", "create_then_release"):
            self.assertIn(t, templates)

    def test_get_backbone_template_has_correct_steps(self):
        tmpl = self.loader.get_template("backbone")
        self.assertIn("steps", tmpl)
        self.assertIn("create_pr", tmpl["steps"])
        self.assertIn("submit_cr", tmpl["steps"])

    def test_get_tools(self):
        tools = self.loader.get_tools()
        self.assertIn("jenkins", tools)
        self.assertIn("servicenow", tools)

    def test_get_lane_actions_contains_rename(self):
        actions = self.loader.get_lane_actions()
        self.assertIn("rename_package", actions)


if __name__ == "__main__":
    unittest.main()
