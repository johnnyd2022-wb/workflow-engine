"""Cases show their owner by name (UX-SWEEP): the queue and case page printed the raw email."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.operational_cases.services.operational_case_service import serialize_case_compact


def _case(owner):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(), title="t", severity="critical", status="open", owner_id=uuid4(), owner=owner,
        due_at=now, next_action="n", version=1, source_type="manual", check_id="c",
        source_entity_type="inventory_item", source_entity_id=uuid4(), previous_case_id=None,
        created_by=uuid4(), created_at=now, updated_at=now,
    )  # fmt: skip


def _owner(first, last, email="hemi@example.test", active=True):
    return SimpleNamespace(first_name=first, last_name=last, email=email, is_active=active)


@pytest.mark.parametrize(
    ("first", "last", "expected"),
    [("Hemi", "Walker", "Hemi Walker"), ("Hemi", None, "Hemi"), (None, None, "hemi@example.test")],
    ids=["full-name", "first-only", "no-name-falls-back-to-email"],
)
def test_owner_name_is_the_persons_name_or_their_email(first, last, expected):
    data = serialize_case_compact(_case(_owner(first, last)))
    assert data["owner_name"] == expected
    assert data["owner_email"] == "hemi@example.test"  # still there for anything that reads it


def test_a_case_with_no_owner_has_no_owner_name():
    assert serialize_case_compact(_case(None))["owner_name"] is None
