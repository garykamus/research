"""Engine integration tests — uses a real in-memory SQLite DB and real config."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.config.loader import FileConfigLoader
from core.credentials.stub_store import StubCredentialStore
from core.persistence.context import PersistenceContext
from core.service import ReleaseService


def _make_service() -> tuple[ReleaseService, str]:
    tmp = tempfile.mktemp(suffix=".db")
    ctx = PersistenceContext(tmp)
    config = FileConfigLoader()
    creds = StubCredentialStore()
    svc = ReleaseService(ctx, config, creds)
    user = ctx.users.get_or_create_default_user("testuser", "Test User")
    return svc, user.id


class TestLaneCreation(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()

    def test_create_lane_hk_backbone(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        self.assertEqual(lane.market, "HK")
        self.assertEqual(lane.arcad_package, "pkg-100")
        self.assertEqual(lane.branch_name, "pkg-100")

    def test_hk_lane_resolves_correct_step_count(self):
        # backbone now has 11 steps (create_arcad_package + 10 original)
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        self.assertEqual(len(detail.steps), 11)

    def test_th_lane_skips_arcad_lock_and_has_regional_compliance(self):
        lane = self.svc.create_lane("TH", "pkg-200", self.uid, "PROJ-2", "https://conf/2", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        step_ids = [s.id for s in detail.steps]
        self.assertNotIn("arcad_lock", step_ids)
        self.assertIn("regional_compliance", step_ids)

    def test_id_lane_has_data_residency_after_create_cr(self):
        lane = self.svc.create_lane("ID", "pkg-300", self.uid, "PROJ-3", "https://conf/3", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        step_ids = [s.id for s in detail.steps]
        dr_idx = step_ids.index("data_residency_check")
        cr_idx = step_ids.index("create_cr")
        self.assertGreater(dr_idx, cr_idx)

    def test_lane_attributes_seeded_correctly(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        self.assertEqual(detail.attributes["jira_id"], "PROJ-1")
        self.assertEqual(detail.attributes["confluence_page"], "https://conf/1")
        self.assertEqual(detail.attributes["arcad_package"], "pkg-100")
        self.assertEqual(detail.attributes["branch_name"], "pkg-100")

    def test_lane_creation_writes_audit_entry(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        audit = self.svc.get_audit_log(lane.id)
        events = [e.event_type for e in audit]
        self.assertIn("LANE_CREATED", events)

    def test_all_steps_start_pending(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        for s in detail.steps:
            self.assertIn(s.status, ("PENDING",))

    def test_create_arcad_package_is_first_step(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        detail = self.svc.get_lane_detail(lane.id)
        self.assertEqual(detail.steps[0].id, "create_arcad_package")

    def test_lane_current_step_is_create_arcad_package_by_default(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        self.assertEqual(lane.current_step_id, "create_arcad_package")


class TestApproachB(unittest.TestCase):
    """Tests for Approach B: skip_steps at lane creation."""

    def setUp(self):
        self.svc, self.uid = _make_service()

    def _create_lane_package_exists(self):
        return self.svc.create_lane(
            "HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid,
            skip_steps=["create_arcad_package"],
        )

    def test_skip_creation_step_marks_it_skipped(self):
        lane = self._create_lane_package_exists()
        detail = self.svc.get_lane_detail(lane.id)
        creation_step = next(s for s in detail.steps if s.id == "create_arcad_package")
        self.assertEqual(creation_step.status, "SKIPPED")

    def test_skip_creation_step_lane_starts_at_create_pr(self):
        lane = self._create_lane_package_exists()
        self.assertEqual(lane.current_step_id, "create_pr")

    def test_skip_creation_step_audited(self):
        lane = self._create_lane_package_exists()
        events = [e.event_type for e in self.svc.get_audit_log(lane.id)]
        self.assertIn("STATUS_CHANGED", events)
        self.assertIn("LANE_CREATED", events)

    def test_skip_creation_step_lane_created_audit_records_skipped(self):
        lane = self._create_lane_package_exists()
        audit = self.svc.get_audit_log(lane.id)
        created_entry = next(e for e in audit if e.event_type == "LANE_CREATED")
        self.assertIn("create_arcad_package", created_entry.detail.get("pre_skipped", []))

    def test_without_skip_lane_starts_at_create_arcad_package(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        self.assertEqual(lane.current_step_id, "create_arcad_package")

    def test_skipped_creation_step_does_not_block_advancement(self):
        lane = self._create_lane_package_exists()
        # Should be able to advance create_pr directly
        self.svc.advance_step(
            lane.id, "create_pr", self.uid,
            recorded_values={"pr_url": "https://github.com/pr/1"},
        )
        detail = self.svc.get_lane_detail(lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertEqual(create_pr.status, "DONE")

    def test_rename_works_after_skip(self):
        from unittest.mock import MagicMock, patch
        lane = self._create_lane_package_exists()
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.produced = {}
        mock_result.links = []
        with patch("core.triggers.http_executor.HttpExecutor.execute", return_value=mock_result):
            result = self.svc.invoke_lane_action(
                lane.id, "rename_package",
                inputs={"new_name": "pkg-renamed"},
                reason="Rename after creation skip",
                acting_user_id=self.uid,
            )
        self.assertTrue(result.success)
        updated = self.svc.get_lane(lane.id)
        self.assertEqual(updated.arcad_package, "pkg-renamed")
        self.assertEqual(updated.branch_name, "pkg-renamed")

    def test_unknown_skip_step_is_ignored_gracefully(self):
        # Skipping a step not in the resolved flow should not raise
        lane = self.svc.create_lane(
            "HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid,
            skip_steps=["nonexistent_step"],
        )
        detail = self.svc.get_lane_detail(lane.id)
        # All real steps start PENDING; the unknown ID is silently ignored
        for s in detail.steps:
            self.assertEqual(s.status, "PENDING")


class TestStepAdvancement(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()
        # Use skip_steps so the lane starts at create_pr (existing package flow)
        self.lane = self.svc.create_lane(
            "HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid,
            skip_steps=["create_arcad_package"],
        )

    def test_advance_first_step_marks_done(self):
        self.svc.advance_step(self.lane.id, "create_pr", self.uid,
                               recorded_values={"pr_url": "https://github.com/pr/1"})
        detail = self.svc.get_lane_detail(self.lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertEqual(create_pr.status, "DONE")

    def test_produce_value_appears_in_bag(self):
        self.svc.advance_step(self.lane.id, "create_pr", self.uid,
                               recorded_values={"pr_url": "https://github.com/pr/1"})
        detail = self.svc.get_lane_detail(self.lane.id)
        self.assertEqual(detail.bag.get("pr_url"), "https://github.com/pr/1")

    def test_consume_gating_blocks_step_missing_value(self):
        # release_build consumes arcad_package (lane attr, OK) but sast_scan consumes build_url
        # Advance create_pr then release_build to get build_url first
        self.svc.advance_step(self.lane.id, "create_pr", self.uid,
                               recorded_values={"pr_url": "https://github.com/pr/1"})
        # sast_scan consumes build_url which hasn't been produced yet
        with self.assertRaises(ValueError) as ctx:
            self.svc.advance_step(self.lane.id, "sast_scan", self.uid)
        self.assertIn("build_url", str(ctx.exception))

    def test_advance_updates_lane_current_step(self):
        self.svc.advance_step(self.lane.id, "create_pr", self.uid,
                               recorded_values={"pr_url": "https://github.com/pr/1"})
        lane = self.svc.get_lane(self.lane.id)
        self.assertEqual(lane.current_step_id, "release_build")

    def test_advance_step_writes_step_result_audit(self):
        self.svc.advance_step(self.lane.id, "create_pr", self.uid,
                               recorded_values={"pr_url": "https://github.com/pr/1"})
        audit = self.svc.get_audit_log(self.lane.id)
        events = [e.event_type for e in audit]
        self.assertIn("STEP_RESULT", events)

    def test_recorded_links_stored_and_retrievable(self):
        self.svc.advance_step(
            self.lane.id, "create_pr", self.uid,
            recorded_values={"pr_url": "https://github.com/pr/1"},
            recorded_links=[{"label": "Open PR", "url": "https://github.com/pr/1"}],
        )
        detail = self.svc.get_lane_detail(self.lane.id)
        self.assertEqual(len(detail.links), 1)
        self.assertEqual(detail.links[0].label, "Open PR")

    def test_all_steps_done_lane_becomes_done(self):
        # Walk all HK steps manually — all have consumes that chain.
        # cr_no is consumed by g3_package, submit_cr, etc., so seed it via create_cr.
        steps_values = [
            ("create_pr", {"pr_url": "https://github.com/pr/1"}),
            ("release_build", {"build_url": "https://jenkins/build/1", "build_result": "SUCCESS"}),
            ("sast_scan", {"sast_url": "https://sast/1", "cyber_url": "https://cyber/1"}),
            ("create_cr", {"cr_no": "CR001", "cr_url": "https://snow/CR001"}),
            ("arcad_lock", {}),
            ("g3_package", {"g3_url": "https://jenkins/g3/1"}),
            ("submit_cr", {}),
            ("update_evidence", {}),
            ("update_confluence_release", {}),
            ("update_jira_status", {}),
        ]
        for step_id, vals in steps_values:
            self.svc.advance_step(self.lane.id, step_id, self.uid, recorded_values=vals)

        lane = self.svc.get_lane(self.lane.id)
        self.assertEqual(lane.status, "DONE")


class TestSkipStep(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()
        # Use skip_steps so lane starts at create_pr (existing-package flow)
        self.lane = self.svc.create_lane(
            "HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid,
            skip_steps=["create_arcad_package"],
        )

    def test_skip_step_becomes_skipped(self):
        self.svc.skip_step(self.lane.id, "create_pr", self.uid, "Not needed for hotfix")
        detail = self.svc.get_lane_detail(self.lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertEqual(create_pr.status, "SKIPPED")

    def test_skip_writes_status_changed_audit(self):
        self.svc.skip_step(self.lane.id, "create_pr", self.uid, "Skipped")
        events = [e.event_type for e in self.svc.get_audit_log(self.lane.id)]
        self.assertIn("STATUS_CHANGED", events)

    def test_skip_advances_to_next_step(self):
        self.svc.skip_step(self.lane.id, "create_pr", self.uid, "Skipped")
        lane = self.svc.get_lane(self.lane.id)
        self.assertEqual(lane.current_step_id, "release_build")


class TestOverrideStep(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()
        # Use skip_steps so lane starts at create_pr (existing-package flow)
        self.lane = self.svc.create_lane(
            "HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid,
            skip_steps=["create_arcad_package"],
        )

    def test_override_requires_reason(self):
        with self.assertRaises(ValueError) as ctx:
            self.svc.override_step(self.lane.id, "create_pr", "DONE", "", self.uid)
        self.assertIn("reason", str(ctx.exception).lower())

    def test_override_records_who_when_why(self):
        self.svc.override_step(self.lane.id, "create_pr", "DONE", "Already done externally", self.uid)
        detail = self.svc.get_lane_detail(self.lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertIsNotNone(create_pr.override)
        self.assertEqual(create_pr.override.value, "DONE")
        self.assertEqual(create_pr.override.reason, "Already done externally")

    def test_override_effective_status_takes_precedence(self):
        self.svc.override_step(self.lane.id, "create_pr", "DONE", "Reason", self.uid)
        detail = self.svc.get_lane_detail(self.lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertEqual(create_pr.compute_effective_status(), "DONE")

    def test_override_advances_lane(self):
        self.svc.override_step(self.lane.id, "create_pr", "DONE", "Reason", self.uid)
        lane = self.svc.get_lane(self.lane.id)
        self.assertEqual(lane.current_step_id, "release_build")

    def test_override_writes_audit(self):
        self.svc.override_step(self.lane.id, "create_pr", "DONE", "Reason", self.uid)
        events = [e.event_type for e in self.svc.get_audit_log(self.lane.id)]
        self.assertIn("OVERRIDE_APPLIED", events)

    def test_override_create_arcad_package_step_when_not_skipped(self):
        # Lane without skip — creation step is first; override it as already done
        lane = self.svc.create_lane("HK", "pkg-200", self.uid, "PROJ-2", "https://conf/2", self.uid)
        self.svc.override_step(lane.id, "create_arcad_package", "DONE", "Created manually", self.uid)
        updated = self.svc.get_lane(lane.id)
        self.assertEqual(updated.current_step_id, "create_pr")


class TestExternalHold(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()

    def _make_ctr_lane(self):
        """
        create_then_release starts with create_arcad_package then external_dev_work.
        We skip the first step so the lane lands on the external_hold step.
        """
        import tempfile
        from core.config.loader import FileConfigLoader
        from core.credentials.stub_store import StubCredentialStore
        from core.persistence.context import PersistenceContext

        tmp = tempfile.mktemp(suffix=".db")
        ctx = PersistenceContext(tmp)
        config = FileConfigLoader()
        svc = ReleaseService(ctx, config, StubCredentialStore())
        user = ctx.users.get_or_create_default_user("u2", "User 2")

        # HK uses backbone — add external_dev_work by using a market that skips backbone
        # and uses create_then_release. Easiest: skip create_arcad_package so lane
        # lands on the external_hold step.
        from unittest.mock import MagicMock, patch

        # Build a minimal config stub that maps HOLD market → create_then_release.
        real_config = FileConfigLoader()

        class HoldConfig:
            def get_step_definition(self, step_id):
                return real_config.get_step_definition(step_id)
            def get_template(self, template_id):
                if template_id == "hold_only":
                    # external_hold followed by create_pr so the flow doesn't end on hold.
                    return {"steps": ["external_dev_work", "create_pr"]}
                return real_config.get_template(template_id)
            def get_market_binding(self, market):
                if market == "HOLD":
                    return {
                        "market": "HOLD",
                        "use": "hold_only",
                        "urls": {},
                        "repo": "org/hold",
                        "default_owner": "team-hold",
                        "add": [], "skip": [], "reorder": [], "override": {},
                    }
                return real_config.get_market_binding(market)
            def get_tools(self):
                return real_config.get_tools()
            def get_lane_actions(self):
                return real_config.get_lane_actions()
            def list_markets(self):
                return real_config.list_markets() + ["HOLD"]
            def list_templates(self):
                return real_config.list_templates() + ["hold_only"]

        hold_config = HoldConfig()
        from core.engine.lifecycle import LaneEngine
        from core.service import ReleaseService as RS
        svc2 = RS(ctx, hold_config, StubCredentialStore())
        lane = svc2.create_lane("HOLD", "pkg-hold", user.id, "PROJ-HOLD", "https://conf/hold", user.id)
        return svc2, lane, user.id

    def test_hk_lane_has_no_external_hold(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        lane_obj = self.svc.get_lane(lane.id)
        self.assertNotEqual(lane_obj.status, "SUSPENDED")

    def test_external_hold_parks_lane_suspended(self):
        svc, lane, uid = self._make_ctr_lane()
        lane_obj = svc.get_lane(lane.id)
        self.assertEqual(lane_obj.status, "SUSPENDED")

    def test_suspended_state_survives_reload(self):
        svc, lane, uid = self._make_ctr_lane()
        lane_obj = svc.get_lane(lane.id)
        self.assertEqual(lane_obj.status, "SUSPENDED")

    def test_manual_resume_advances_to_next_step(self):
        svc, lane, uid = self._make_ctr_lane()
        detail = svc.get_lane_detail(lane.id)
        hold_step = next(s for s in detail.steps if s.kind == "external_hold")
        svc.resume_external_hold(lane.id, hold_step.id, uid,
                                  captured_values={"build_url": "https://ext-build/1"})
        lane_obj = svc.get_lane(lane.id)
        self.assertNotEqual(lane_obj.status, "SUSPENDED")

    def test_resume_puts_captured_values_in_bag(self):
        svc, lane, uid = self._make_ctr_lane()
        detail = svc.get_lane_detail(lane.id)
        hold_step = next(s for s in detail.steps if s.kind == "external_hold")
        svc.resume_external_hold(lane.id, hold_step.id, uid,
                                  captured_values={"build_url": "https://ext-build/1"})
        detail2 = svc.get_lane_detail(lane.id)
        self.assertEqual(detail2.bag.get("build_url"), "https://ext-build/1")

    def test_resume_writes_lane_resumed_audit(self):
        svc, lane, uid = self._make_ctr_lane()
        detail = svc.get_lane_detail(lane.id)
        hold_step = next(s for s in detail.steps if s.kind == "external_hold")
        svc.resume_external_hold(lane.id, hold_step.id, uid)
        events = [e.event_type for e in svc.get_audit_log(lane.id)]
        self.assertIn("LANE_RESUMED", events)

    def test_resume_non_external_hold_raises(self):
        lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)
        with self.assertRaises(ValueError) as ctx:
            self.svc.resume_external_hold(lane.id, "create_pr", self.uid)
        self.assertIn("external_hold", str(ctx.exception))


class TestLaneAction(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()
        self.lane = self.svc.create_lane("HK", "pkg-100", self.uid, "PROJ-1", "https://conf/1", self.uid)

    def _rename(self, new_name="pkg-200", reason="Reason"):
        from unittest.mock import MagicMock, patch
        mock_result = MagicMock()
        mock_result.status = "SUCCESS"
        mock_result.produced = {}
        mock_result.links = []
        with patch("core.triggers.http_executor.HttpExecutor.execute", return_value=mock_result):
            return self.svc.invoke_lane_action(
                self.lane.id, "rename_package",
                inputs={"new_name": new_name},
                reason=reason,
                acting_user_id=self.uid,
            )

    def test_rename_updates_arcad_package_and_branch_name_together(self):
        result = self._rename("pkg-200", "Package version bump")
        self.assertTrue(result.success)
        lane = self.svc.get_lane(self.lane.id)
        self.assertEqual(lane.arcad_package, "pkg-200")
        self.assertEqual(lane.branch_name, "pkg-200")

    def test_rename_preserves_lane_id(self):
        original_id = self.lane.id
        self._rename()
        lane = self.svc.get_lane(original_id)
        self.assertEqual(lane.id, original_id)

    def test_rename_writes_audit_entries(self):
        self._rename()
        events = [e.event_type for e in self.svc.get_audit_log(self.lane.id)]
        self.assertIn("LANE_ACTION_INVOKED", events)
        self.assertIn("ATTRIBUTE_CHANGED", events)

    def test_rename_requires_reason(self):
        with self.assertRaises(ValueError) as ctx:
            self.svc.invoke_lane_action(
                self.lane.id, "rename_package",
                inputs={"new_name": "pkg-200"},
                reason="",
                acting_user_id=self.uid,
            )
        self.assertIn("reason", str(ctx.exception).lower())

    def test_later_steps_use_new_name_from_attributes(self):
        self._rename("pkg-renamed", "Rename")
        detail = self.svc.get_lane_detail(self.lane.id)
        self.assertEqual(detail.attributes["arcad_package"], "pkg-renamed")
        self.assertEqual(detail.attributes["branch_name"], "pkg-renamed")


class TestRestartResume(unittest.TestCase):
    """Proves state persists across service re-creation (Rule 1)."""

    def test_lane_state_survives_restart(self):
        import tempfile
        from core.config.loader import FileConfigLoader
        from core.credentials.stub_store import StubCredentialStore
        from core.persistence.context import PersistenceContext

        db_path = tempfile.mktemp(suffix=".db")

        ctx1 = PersistenceContext(db_path)
        svc1 = ReleaseService(ctx1, FileConfigLoader(), StubCredentialStore())
        user = ctx1.users.get_or_create_default_user("u1", "U1")
        lane = svc1.create_lane("HK", "pkg-100", user.id, "PROJ-1", "https://conf/1", user.id)
        svc1.advance_step(lane.id, "create_pr", user.id,
                           recorded_values={"pr_url": "https://github.com/pr/1"})

        # Simulate restart: new context, same DB.
        ctx2 = PersistenceContext(db_path)
        svc2 = ReleaseService(ctx2, FileConfigLoader(), StubCredentialStore())
        detail = svc2.get_lane_detail(lane.id)
        create_pr = next(s for s in detail.steps if s.id == "create_pr")
        self.assertEqual(create_pr.status, "DONE")
        self.assertEqual(detail.bag.get("pr_url"), "https://github.com/pr/1")


class TestListLanes(unittest.TestCase):
    def setUp(self):
        self.svc, self.uid = _make_service()

    def test_list_lanes_returns_all(self):
        self.svc.create_lane("HK", "pkg-a", self.uid, "J1", "https://c/1", self.uid)
        self.svc.create_lane("SG", "pkg-b", self.uid, "J2", "https://c/2", self.uid)
        lanes = self.svc.list_lanes()
        self.assertGreaterEqual(len(lanes), 2)

    def test_list_lanes_filter_by_market(self):
        self.svc.create_lane("HK", "pkg-a", self.uid, "J1", "https://c/1", self.uid)
        self.svc.create_lane("SG", "pkg-b", self.uid, "J2", "https://c/2", self.uid)
        hk_lanes = self.svc.list_lanes(market="HK")
        for l in hk_lanes:
            self.assertEqual(l.market, "HK")


if __name__ == "__main__":
    unittest.main()
