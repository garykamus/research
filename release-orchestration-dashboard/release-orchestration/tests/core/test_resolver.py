from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.config.loader import FileConfigLoader
from core.config.resolver import LaneResolver, ResolutionError


class TestLaneResolver(unittest.TestCase):
    def setUp(self):
        self.loader = FileConfigLoader()
        self.resolver = LaneResolver(self.loader)

    def test_hk_backbone_correct_order(self):
        steps = self.resolver.resolve("HK", {})
        ids = [s["_step_id"] for s in steps]
        expected = [
            "create_arcad_package",
            "create_pr", "release_build", "sast_scan", "create_cr",
            "arcad_lock", "g3_package", "submit_cr",
            "update_evidence", "update_confluence_release", "update_jira_status",
        ]
        self.assertEqual(ids, expected)

    def test_th_adds_regional_compliance_before_submit_cr(self):
        steps = self.resolver.resolve("TH", {})
        ids = [s["_step_id"] for s in steps]
        self.assertIn("regional_compliance", ids)
        rc_idx = ids.index("regional_compliance")
        sc_idx = ids.index("submit_cr")
        self.assertLess(rc_idx, sc_idx)

    def test_th_skips_arcad_lock(self):
        steps = self.resolver.resolve("TH", {})
        ids = [s["_step_id"] for s in steps]
        self.assertNotIn("arcad_lock", ids)

    def test_id_uses_regulated_flow_and_adds_data_residency_after_create_cr(self):
        steps = self.resolver.resolve("ID", {})
        ids = [s["_step_id"] for s in steps]
        self.assertIn("regional_compliance", ids)
        self.assertIn("data_residency_check", ids)
        dr_idx = ids.index("data_residency_check")
        cr_idx = ids.index("create_cr")
        self.assertGreater(dr_idx, cr_idx)

    def test_id_has_extra_field_on_create_cr(self):
        steps = self.resolver.resolve("ID", {})
        cr_step = next(s for s in steps if s["_step_id"] == "create_cr")
        field_keys = [f["key"] for f in cr_step.get("view_config", {}).get("fields", [])]
        self.assertIn("residency_zone", field_keys)

    def test_create_then_release_template_has_external_hold(self):
        # Use HK binding but override template temporarily — instead test the
        # template directly via the loader.
        from core.config.loader import FileConfigLoader
        loader = FileConfigLoader()
        tmpl = loader.get_template("create_then_release")
        self.assertIn("external_dev_work", tmpl["steps"])

    def test_resolution_error_on_unknown_step(self):
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.get_market_binding.return_value = {
            "use": "test_tmpl",
            "add": [], "skip": [], "reorder": [], "override": {},
        }
        mock_config.get_template.return_value = {"steps": ["nonexistent_step"]}
        mock_config.get_step_definition.side_effect = KeyError("nonexistent_step")

        resolver = LaneResolver(mock_config)
        with self.assertRaises(ResolutionError) as ctx:
            resolver.resolve("MOCK", {})
        self.assertIn("nonexistent_step", str(ctx.exception))

    def test_resolution_error_on_bad_add_anchor(self):
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.get_market_binding.return_value = {
            "use": "test_tmpl",
            "add": [{"step": "new_step", "before": "no_such_anchor"}],
            "skip": [], "reorder": [], "override": {},
        }
        mock_config.get_template.return_value = {"steps": ["create_pr"]}
        mock_config.get_step_definition.return_value = {
            "mode": "MANUAL", "kind": "standard",
            "produces": [], "consumes": [], "view": "generic",
            "trigger": {"type": "none"}, "view_config": {},
        }

        resolver = LaneResolver(mock_config)
        with self.assertRaises(ResolutionError) as ctx:
            resolver.resolve("MOCK", {})
        self.assertIn("no_such_anchor", str(ctx.exception))

    def test_value_bag_coherence_error_when_consume_missing_producer(self):
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.get_market_binding.return_value = {
            "use": "test_tmpl", "add": [], "skip": [], "reorder": [], "override": {},
        }
        mock_config.get_template.return_value = {"steps": ["step_a", "step_b"]}

        def get_step(sid):
            if sid == "step_a":
                return {"mode": "MANUAL", "kind": "standard", "produces": [],
                        "consumes": [], "view": "generic",
                        "trigger": {"type": "none"}, "view_config": {}}
            return {"mode": "MANUAL", "kind": "standard", "produces": [],
                    "consumes": ["missing_key"], "view": "generic",
                    "trigger": {"type": "none"}, "view_config": {}}

        mock_config.get_step_definition.side_effect = get_step
        resolver = LaneResolver(mock_config)
        with self.assertRaises(ResolutionError) as ctx:
            resolver.resolve("MOCK", {})
        self.assertIn("missing_key", str(ctx.exception))

    def test_all_placeholder_markets_pass_startup_validation(self):
        results = self.resolver.validate_all_markets()
        for market, errors in results.items():
            self.assertEqual(errors, [], f"Market {market} has resolution errors: {errors}")

    def test_no_duplicate_step_ids(self):
        for market in self.loader.list_markets():
            steps = self.resolver.resolve(market, {})
            ids = [s["_step_id"] for s in steps]
            self.assertEqual(len(ids), len(set(ids)), f"Duplicate step IDs in {market}: {ids}")

    def test_seq_order_is_contiguous(self):
        steps = self.resolver.resolve("HK", {})
        orders = [s["_order"] for s in steps]
        self.assertEqual(orders, list(range(len(steps))))


if __name__ == "__main__":
    unittest.main()
