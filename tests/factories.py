"""factory-boy factories for test data.

Wrap the repository pattern (see .agents/conventions.md §2) rather than constructing
models directly — factory-created rows go through the same code path (defaults,
normalization, integrity checks) as the app, not a shortcut around it.

Owned by the test-fixtures skill. Add a factory here, not a one-off in a test file, the
moment a second test needs the same kind of row.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import factory

from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.feature_subscription import FeatureSubscription
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.db.repositories.wastage_repo import WastageRepository
from app.features.operational_cases.models.operational_case import OperationalCase
from app.features.operational_cases.repositories.operational_case_repo import OperationalCaseRepository

# Low bcrypt cost in tests only — bcrypt encodes its own cost factor in the hash, so a
# password hashed here still verifies correctly through the real login flow; this only
# saves wall-clock time in the suite. Never reuse this constant outside tests.
_TEST_BCRYPT_ROUNDS = 4
DEFAULT_TEST_PASSWORD = "Test-Passw0rd!1"


class OrganisationFactory(factory.Factory):
    class Meta:
        model = Organisation

    # UUID-suffixed, not a bare per-process sequence: `n` restarts at 0 every test-process
    # run while rows persist in the shared test DB, so a run whose teardown fails poisons
    # the next run's org at that same number — a name collision presenting as an unrelated
    # failure wherever the colliding number lands next.
    name = factory.Sequence(lambda n: f"Test Org {n}-{uuid.uuid4().hex[:8]}")

    @classmethod
    def _create(cls, model_class, name, **kwargs):
        return OrganisationRepository(db_session()).create_org(name)


class UserFactory(factory.Factory):
    class Meta:
        model = User

    org_id = None
    email = factory.Sequence(lambda n: f"test-user-{n}@example.test")
    role = UserRole.MEMBER

    @classmethod
    def _create(cls, model_class, org_id, email, role, **kwargs):
        if org_id is None:
            raise ValueError("UserFactory requires org_id, e.g. UserFactory(org_id=org.id)")
        password_hash = bcrypt.hashpw(
            DEFAULT_TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=_TEST_BCRYPT_ROUNDS)
        ).decode()
        return UserRepository(db_session()).create_user(
            org_id=org_id, email=email, password_hash=password_hash, role=role, **kwargs
        )


class InventoryItemFactory(factory.Factory):
    """An inventory item created through the repository, so its quantity write goes through
    the REPOSITORY_CREATE authorized path and the quantity guard — never a raw Model(...)
    that would bypass the very guard tenant/inventory tests need to exercise.
    """

    class Meta:
        model = InventoryItem

    org_id = None
    name = factory.Sequence(lambda n: f"Test Item {n}")
    quantity = "10"
    unit = "kg"
    inventory_type = "raw_material"

    @classmethod
    def _create(cls, model_class, org_id, name, quantity, unit, inventory_type, **kwargs):
        if org_id is None:
            raise ValueError("InventoryItemFactory requires org_id, e.g. InventoryItemFactory(org_id=org.id)")
        return InventoryRepository(db_session()).create_inventory_item(
            org_id=org_id,
            name=name,
            quantity=quantity,
            unit=unit,
            inventory_type=inventory_type,
            **kwargs,
        )


class ProcessFactory(factory.Factory):
    """A process created through the repository (which also writes its first version row)."""

    class Meta:
        model = Process

    org_id = None
    name = factory.Sequence(lambda n: f"Test Process {n}")
    description = ""
    is_draft = False

    @classmethod
    def _create(cls, model_class, org_id, name, description, is_draft, **kwargs):
        if org_id is None:
            raise ValueError("ProcessFactory requires org_id, e.g. ProcessFactory(org_id=org.id)")
        return ProcessRepository(db_session()).create_process(
            org_id=org_id, name=name, description=description, is_draft=is_draft, **kwargs
        )


class ExecutionFactory(factory.Factory):
    """An execution of a process. Requires both org_id and the process_id it runs."""

    class Meta:
        model = Execution

    org_id = None
    process_id = None

    @classmethod
    def _create(cls, model_class, org_id, process_id, **kwargs):
        if org_id is None or process_id is None:
            raise ValueError("ExecutionFactory requires org_id and process_id")
        return ExecutionRepository(db_session()).create_execution(org_id=org_id, process_id=process_id, **kwargs)


class WastageFactory(factory.Factory):
    """A wastage record created through the repository. Requires the org and the inventory
    item it is wasting. The repository records the wastage row only; it does not deduct the
    item's quantity (that is the route handler's job) — so this factory is for exercising
    wastage records themselves (e.g. org isolation), not the full disposal flow.
    """

    class Meta:
        model = InventoryWastage

    org_id = None
    inventory_item_id = None
    quantity_wasted = "1"
    unit = "kg"
    reason = "test wastage"

    @classmethod
    def _create(cls, model_class, org_id, inventory_item_id, quantity_wasted, unit, reason, **kwargs):
        if org_id is None or inventory_item_id is None:
            raise ValueError("WastageFactory requires org_id and inventory_item_id")
        return WastageRepository(db_session()).create_wastage_record(
            org_id=org_id,
            inventory_item_id=inventory_item_id,
            quantity_wasted=quantity_wasted,
            unit=unit,
            reason=reason,
            **kwargs,
        )


class FeatureSubscriptionFactory(factory.Factory):
    """A per-org feature entitlement grant, created through its repository."""

    class Meta:
        model = FeatureSubscription

    org_id = None
    feature_key = "compliant"

    @classmethod
    def _create(cls, model_class, org_id, feature_key, **kwargs):
        if org_id is None:
            raise ValueError(
                "FeatureSubscriptionFactory requires org_id, e.g. FeatureSubscriptionFactory(org_id=org.id)"
            )
        return FeatureSubscriptionRepository(db_session()).grant(org_id, feature_key, **kwargs)


def _default_case_snapshot():
    return {
        "schema_version": 1,
        "check_id": "untracked_items",
        "source_entity_type": "inventory_item",
        "source_entity_id": str(uuid.uuid4()),
        "item_name": "Test Untracked Item",
        "unit": "kg",
        "quantity": "5",
        "remaining_balance_to_reconcile": None,
        "source_execution_id": None,
        "source_execution_step_id": None,
        "producing_step_id": None,
        "observed_at": datetime.now(UTC).isoformat(),
        "adapter_version": "untracked_items_v1",
        "critical_reason": "positive_untracked_stock",
        "truncated_fields": [],
    }


class OperationalCaseFactory(factory.Factory):
    """A case created through the repository's direct row constructor -- bypasses the
    service's eligibility pipeline on purpose, since that pipeline is business logic
    under test elsewhere, not fixture setup (see operational_case_repo.create_case)."""

    class Meta:
        model = OperationalCase

    org_id = None
    owner_id = None
    created_by = None
    source_entity_id = factory.LazyFunction(uuid.uuid4)
    title = factory.Sequence(lambda n: f"Untracked stock: Test Item {n}")
    next_action = "Check batch output and reconcile the remaining quantity"
    due_at = factory.LazyFunction(lambda: datetime.now(UTC) + timedelta(days=1))
    source_snapshot = factory.LazyFunction(_default_case_snapshot)

    @classmethod
    def _create(
        cls,
        model_class,
        org_id,
        owner_id,
        created_by,
        source_entity_id,
        title,
        next_action,
        due_at,
        source_snapshot,
        **kwargs,
    ):
        if org_id is None or owner_id is None or created_by is None:
            raise ValueError("OperationalCaseFactory requires org_id, owner_id and created_by")
        snapshot = dict(source_snapshot)
        snapshot["source_entity_id"] = str(source_entity_id)
        return OperationalCaseRepository(db_session()).create_case(
            org_id=org_id,
            title=title,
            source_entity_id=source_entity_id,
            source_snapshot=snapshot,
            owner_id=owner_id,
            due_at=due_at,
            next_action=next_action,
            created_by=created_by,
            **kwargs,
        )
