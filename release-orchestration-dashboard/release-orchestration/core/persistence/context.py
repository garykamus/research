from __future__ import annotations

from .dal import (
    AuditDAL,
    CredentialDAL,
    LaneDAL,
    OverrideDAL,
    RecordedLinkDAL,
    RecordedValueDAL,
    StepInstanceDAL,
    TriggerAttemptDAL,
    UserDAL,
    ValueBagDAL,
)
from .database import Database


class PersistenceContext:
    """Single entry-point holding the Database and all DAL instances."""

    def __init__(self, db_path: str) -> None:
        self.db = Database(db_path)
        self.users = UserDAL(self.db)
        self.lanes = LaneDAL(self.db)
        self.steps = StepInstanceDAL(self.db)
        self.overrides = OverrideDAL(self.db)
        self.bag = ValueBagDAL(self.db)
        self.links = RecordedLinkDAL(self.db)
        self.recorded_values = RecordedValueDAL(self.db)
        self.audit = AuditDAL(self.db)
        self.trigger_attempts = TriggerAttemptDAL(self.db)
        self.credentials = CredentialDAL(self.db)
