from __future__ import annotations

from typing import TYPE_CHECKING, Type

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

_REGISTRY: dict[str, Type] = {}


def register(view_name: str, widget_class: Type) -> None:
    _REGISTRY[view_name] = widget_class


def get_view_class(view_name: str) -> Type:
    """Return the registered class for view_name, falling back to GenericStepView."""
    if view_name in _REGISTRY:
        return _REGISTRY[view_name]
    from ui.stepviews.generic_view import GenericStepView
    return GenericStepView


def _auto_register() -> None:
    from ui.stepviews.generic_view import GenericStepView
    from ui.stepviews.external_hold_view import ExternalHoldView
    from ui.stepviews.cr_creation_view import CrCreationView
    from ui.stepviews.evidence_update_view import EvidenceUpdateView
    from ui.stepviews.confluence_release_view import ConfluenceReleaseView
    register("generic", GenericStepView)
    register("external_hold", ExternalHoldView)
    register("cr_creation", CrCreationView)
    register("evidence_update", EvidenceUpdateView)
    register("confluence_release", ConfluenceReleaseView)
