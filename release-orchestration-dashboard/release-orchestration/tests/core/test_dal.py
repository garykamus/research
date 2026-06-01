"""Round-trip tests for each DAL class using an in-memory SQLite database."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

# Ensure the project root is on the path when running from any directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.models import (
    AuditEntry,
    Lane,
    Override,
    RecordedLink,
    RecordedValue,
    StepInstance,
    User,
)
from core.persistence.context import PersistenceContext


def _make_ctx() -> tuple[PersistenceContext, str]:
    tmp = tempfile.mktemp(suffix=".db")
    ctx = PersistenceContext(tmp)
    return ctx, tmp


def _seed_user(ctx: PersistenceContext) -> User:
    return ctx.users.create_user("testuser", "Test User")


def _seed_lane(ctx: PersistenceContext, user: User) -> Lane:
    import uuid
    from datetime import datetime, timezone
    lane = Lane(
        id=str(uuid.uuid4()),
        market="HK",
        arcad_package="pkg-001",
        branch_name="pkg-001",
        owner_user_id=user.id,
        created_by_user_id=user.id,
        created_at=datetime.now(timezone.utc).isoformat(),
        workflow_template_id="backbone",
        status="ACTIVE",
        current_step_id=None,
    )
    ctx.lanes.insert_lane(lane)
    return lane


def _seed_step(ctx: PersistenceContext, lane: Lane) -> StepInstance:
    step = StepInstance(
        id="create_pr",
        lane_id=lane.id,
        seq_order=1,
        definition_ref="create_pr",
        label="Create PR on GitHub",
        kind="standard",
        mode="HYBRID",
        view="generic",
        status="PENDING",
        auto_result="UNKNOWN",
        produces=["pr_url"],
        consumes=["arcad_package"],
        trigger_ref={"type": "none"},
        post_actions=[],
        view_config={},
        entered_at=None,
        completed_at=None,
        last_acted_by_user_id=None,
    )
    ctx.steps.insert_step_instances([step])
    return step


class TestUserDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, self.db_path = _make_ctx()

    def test_create_and_get_user(self):
        user = self.ctx.users.create_user("alice", "Alice Smith")
        fetched = self.ctx.users.get_user(user.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.username, "alice")

    def test_get_or_create_default_user_idempotent(self):
        u1 = self.ctx.users.get_or_create_default_user("bob", "Bob")
        u2 = self.ctx.users.get_or_create_default_user("bob", "Bob")
        self.assertEqual(u1.id, u2.id)

    def test_get_missing_user_returns_none(self):
        self.assertIsNone(self.ctx.users.get_user("does-not-exist"))


class TestLaneDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)

    def test_insert_and_get_lane(self):
        lane = _seed_lane(self.ctx, self.user)
        fetched = self.ctx.lanes.get_lane(lane.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.market, "HK")
        self.assertEqual(fetched.arcad_package, "pkg-001")
        self.assertEqual(fetched.branch_name, "pkg-001")

    def test_list_lanes_filter_by_market(self):
        _seed_lane(self.ctx, self.user)
        results = self.ctx.lanes.list_lanes(market="HK")
        self.assertEqual(len(results), 1)
        results_sg = self.ctx.lanes.list_lanes(market="SG")
        self.assertEqual(len(results_sg), 0)

    def test_update_lane_status(self):
        lane = _seed_lane(self.ctx, self.user)
        self.ctx.lanes.update_lane_status(lane.id, "DONE", None)
        fetched = self.ctx.lanes.get_lane(lane.id)
        self.assertEqual(fetched.status, "DONE")

    def test_update_lane_package_keeps_alignment(self):
        lane = _seed_lane(self.ctx, self.user)
        self.ctx.lanes.update_lane_package(lane.id, "pkg-002", "pkg-002")
        fetched = self.ctx.lanes.get_lane(lane.id)
        self.assertEqual(fetched.arcad_package, "pkg-002")
        self.assertEqual(fetched.branch_name, "pkg-002")

    def test_lane_attributes_round_trip(self):
        lane = _seed_lane(self.ctx, self.user)
        self.ctx.lanes.set_lane_attributes(lane.id, {
            "jira_id": "PROJ-001",
            "confluence_page": "https://confluence/page/1",
        })
        attrs = self.ctx.lanes.get_lane_attributes(lane.id)
        self.assertEqual(attrs["jira_id"], "PROJ-001")
        self.assertEqual(attrs["confluence_page"], "https://confluence/page/1")

    def test_set_lane_attribute_upserts(self):
        lane = _seed_lane(self.ctx, self.user)
        self.ctx.lanes.set_lane_attribute(lane.id, "owner", "team-hk")
        self.ctx.lanes.set_lane_attribute(lane.id, "owner", "team-hk-updated")
        attrs = self.ctx.lanes.get_lane_attributes(lane.id)
        self.assertEqual(attrs["owner"], "team-hk-updated")


class TestStepInstanceDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)
        self.lane = _seed_lane(self.ctx, self.user)

    def test_insert_and_list(self):
        _seed_step(self.ctx, self.lane)
        steps = self.ctx.steps.list_step_instances(self.lane.id)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].id, "create_pr")
        self.assertEqual(steps[0].produces, ["pr_url"])

    def test_get_step_instance(self):
        _seed_step(self.ctx, self.lane)
        step = self.ctx.steps.get_step_instance(self.lane.id, "create_pr")
        self.assertIsNotNone(step)
        self.assertEqual(step.mode, "HYBRID")

    def test_update_step_status(self):
        _seed_step(self.ctx, self.lane)
        self.ctx.steps.update_step_status(
            self.lane.id, "create_pr", "DONE", "SUCCESS", self.user.id
        )
        step = self.ctx.steps.get_step_instance(self.lane.id, "create_pr")
        self.assertEqual(step.status, "DONE")
        self.assertEqual(step.auto_result, "SUCCESS")


class TestOverrideDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)
        self.lane = _seed_lane(self.ctx, self.user)
        _seed_step(self.ctx, self.lane)

    def test_upsert_and_get(self):
        from datetime import datetime, timezone
        ov = Override(
            step_instance_id="create_pr",
            lane_id=self.lane.id,
            value="DONE",
            reason="Already merged externally",
            who_user_id=self.user.id,
            applied_at=datetime.now(timezone.utc).isoformat(),
        )
        self.ctx.overrides.upsert_override(ov)
        fetched = self.ctx.overrides.get_override(self.lane.id, "create_pr")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.value, "DONE")
        self.assertEqual(fetched.reason, "Already merged externally")

    def test_upsert_replaces(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for reason in ("first reason", "updated reason"):
            self.ctx.overrides.upsert_override(Override(
                step_instance_id="create_pr",
                lane_id=self.lane.id,
                value="DONE",
                reason=reason,
                who_user_id=self.user.id,
                applied_at=now,
            ))
        fetched = self.ctx.overrides.get_override(self.lane.id, "create_pr")
        self.assertEqual(fetched.reason, "updated reason")

    def test_missing_returns_none(self):
        self.assertIsNone(self.ctx.overrides.get_override(self.lane.id, "nonexistent"))


class TestValueBagDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)
        self.lane = _seed_lane(self.ctx, self.user)

    def test_upsert_and_get_bag(self):
        self.ctx.bag.upsert_value(self.lane.id, "pr_url", "https://github.com/pr/1", "create_pr", "api")
        bag = self.ctx.bag.get_bag(self.lane.id)
        self.assertEqual(bag["pr_url"], "https://github.com/pr/1")

    def test_upsert_overwrites(self):
        self.ctx.bag.upsert_value(self.lane.id, "pr_url", "old", "create_pr", "manual")
        self.ctx.bag.upsert_value(self.lane.id, "pr_url", "new", "create_pr", "api")
        self.assertEqual(self.ctx.bag.get_value(self.lane.id, "pr_url"), "new")

    def test_get_value_missing_returns_none(self):
        self.assertIsNone(self.ctx.bag.get_value(self.lane.id, "missing_key"))


class TestRecordedLinkDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)
        self.lane = _seed_lane(self.ctx, self.user)
        _seed_step(self.ctx, self.lane)

    def test_insert_and_get_for_step(self):
        import uuid
        from datetime import datetime, timezone
        link = RecordedLink(
            id=str(uuid.uuid4()),
            step_instance_id="create_pr",
            lane_id=self.lane.id,
            label="Open PR",
            url="https://github.com/pr/1",
            recorded_by_user_id=self.user.id,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.ctx.links.insert_link(link)
        links = self.ctx.links.get_links_for_step(self.lane.id, "create_pr")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://github.com/pr/1")

    def test_get_links_for_lane(self):
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.ctx.links.insert_link(RecordedLink(
            id=str(uuid.uuid4()), step_instance_id="create_pr",
            lane_id=self.lane.id, label="L1", url="https://a.com",
            recorded_by_user_id=self.user.id, recorded_at=now,
        ))
        all_links = self.ctx.links.get_links_for_lane(self.lane.id)
        self.assertEqual(len(all_links), 1)


class TestAuditDAL(unittest.TestCase):
    def setUp(self):
        self.ctx, _ = _make_ctx()
        self.user = _seed_user(self.ctx)
        self.lane = _seed_lane(self.ctx, self.user)

    def test_insert_and_get_entries(self):
        import uuid
        from datetime import datetime, timezone
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            lane_id=self.lane.id,
            step_instance_id=None,
            event_type="LANE_CREATED",
            actor_user_id=self.user.id,
            at=datetime.now(timezone.utc).isoformat(),
            detail={"market": "HK"},
        )
        self.ctx.audit.insert_entry(entry)
        entries = self.ctx.audit.get_entries(self.lane.id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].event_type, "LANE_CREATED")
        self.assertEqual(entries[0].detail["market"], "HK")


if __name__ == "__main__":
    unittest.main()
