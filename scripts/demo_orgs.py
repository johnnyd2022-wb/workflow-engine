#!/usr/bin/env python3
"""Load the two demo organisations used by docs/demo-script.md (GL-C06).

  load     create both orgs and print their sign-ins
  status   say whether they exist
  purge    delete them (only orgs this script created, by name)

The orgs:

  Demo · Kōwhai Distillery (new)        signed up a minute ago: no stock, no workflows. For
                                        "how fast do I get value": the setup guide, opening
                                        stock, the first workflow, the first batch.
  Demo · Harbour Spirits (established)  months of history: stock with suppliers and expiries,
                                        gin and limoncello batches traced to Xero sales, excise
                                        periods (two lodged, a backlog), a sale to a duty free
                                        shop, NP3 evidence, licences, contract orders, a
                                        stocktake. For specific questions.

Both are built from the screenshot harness's seeds (scripts/ui_shots.py), which are realistic
but synthetic. Whistlebird's own replay (scripts/replay_whistlebird.sh) has real customers and
suppliers, so it is not used for demos.

Local test database only, like the harness:

  env -u ENVIRONMENT uv run python scripts/demo_orgs.py load
"""

from __future__ import annotations

import argparse
import secrets
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import ui_shots  # noqa: E402 -- the seeds and the purge live there

PREFIX = "Demo · "
NEW = PREFIX + "Kōwhai Distillery (new)"
ESTABLISHED = PREFIX + "Harbour Spirits (established)"
# The established org's history, in the order the seeds depend on each other.
ESTABLISHED_SEEDS = (
    "stock", "lineage", "sales", "customers", "suppliers", "compliance", "excise", "transfers",
    "production", "planner", "contracts", "np3", "licensing", "tasks",
)  # fmt: skip


def say(*parts) -> None:
    print("demo:", *parts)


def _orgs(db):
    from app.core.db.models.organisation import Organisation

    return db.query(Organisation).filter(Organisation.name.like(PREFIX + "%")).all()


def _make_org(db, name: str, email: str, password: str):
    from app.core.db.models.user import UserRole
    from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
    from app.core.security.auth_service import AuthService
    from tests.factories import OrganisationFactory, UserFactory

    org = OrganisationFactory(name=name)
    user = UserFactory(org_id=org.id, email=email, role=UserRole.ADMIN)
    user.password_hash = AuthService.hash_password(password)
    # The offer being demonstrated is Compliance (NZ Alcohol).
    FeatureSubscriptionRepository(db).grant(org.id, "compliant")
    db.commit()
    return org, user


def cmd_load(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.repositories.inventory_repo import InventoryRepository

    db = db_session()
    if _orgs(db):
        say("the demo orgs already exist; run `purge` first")
        return 2
    run = uuid.uuid4().hex[:6]
    password = secrets.token_urlsafe(12)
    new_org, new_user = _make_org(db, NEW, f"demo-new-{run}@example.test", password)
    org, user = _make_org(db, ESTABLISHED, f"demo-established-{run}@example.test", password)
    inv = InventoryRepository(db)
    for kind in ESTABLISHED_SEEDS:
        getattr(ui_shots, f"_seed_{kind}")(db, org.id, inv)
        say(f"seeded {kind}")
    say("ready. Sign in at /, with the password below for both:")
    say(f"  {NEW}: {new_user.email}")
    say(f"  {ESTABLISHED}: {user.email}")
    say(f"  password: {password}")
    return 0


def cmd_status(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.models.user import User

    db = db_session()
    orgs = _orgs(db)
    if not orgs:
        say("no demo orgs loaded")
    for org in orgs:
        emails = [u.email for u in db.query(User).filter(User.org_id == org.id)]
        say(f"{org.name}: {', '.join(emails)}")
    return 0


def cmd_purge(_args) -> int:
    ui_shots._require_local()
    from app.core.db import db_session
    from app.core.db.models.user import User

    db = db_session()
    for org in _orgs(db):
        if not org.name.startswith(PREFIX):  # the query already says so; checked again before deleting
            continue
        admin = db.query(User).filter(User.org_id == org.id).first()
        ui_shots.purge_seeded_org(db, org.id, admin.id if admin else None)
        say(f"purged {org.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("load", "status", "purge"))
    args = parser.parse_args()
    return {"load": cmd_load, "status": cmd_status, "purge": cmd_purge}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
