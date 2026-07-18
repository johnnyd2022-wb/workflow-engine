"""factory-boy factories for test data.

Wrap the repository pattern (see .agents/conventions.md §2) rather than constructing
models directly — factory-created rows go through the same code path (defaults,
normalization, integrity checks) as the app, not a shortcut around it.

Owned by the test-fixtures skill. Add a factory here, not a one-off in a test file, the
moment a second test needs the same kind of row.
"""

import bcrypt
import factory

from app.core.db import db_session
from app.core.db.models.execution import Execution
from app.core.db.models.inventory_item import InventoryItem
from app.core.db.models.inventory_wastage import InventoryWastage
from app.core.db.models.organisation import Organisation
from app.core.db.models.process import Process
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.execution_repo import ExecutionRepository
from app.core.db.repositories.inventory_repo import InventoryRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.process_repo import ProcessRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.db.repositories.wastage_repo import WastageRepository

# Low bcrypt cost in tests only — bcrypt encodes its own cost factor in the hash, so a
# password hashed here still verifies correctly through the real login flow; this only
# saves wall-clock time in the suite. Never reuse this constant outside tests.
_TEST_BCRYPT_ROUNDS = 4
DEFAULT_TEST_PASSWORD = "Test-Passw0rd!1"


class OrganisationFactory(factory.Factory):
    class Meta:
        model = Organisation

    name = factory.Sequence(lambda n: f"Test Org {n}")

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
