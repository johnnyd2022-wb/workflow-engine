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
from app.core.db.models.organisation import Organisation
from app.core.db.models.user import User, UserRole
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository

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
