"""Admin CLI commands for organisations and users.

Anything that changes data goes through `app.admin_site.operations`, the same code the
admin site runs, so the two cannot drift apart and both leave an audit entry.
"""

from uuid import UUID

import click

from app.admin_site import operations as ops
from app.core.db import db_session
from app.core.db.models.organisation import OrganisationStatus
from app.core.db.repositories.backup_code_repo import BackupCodeRepository
from app.core.db.repositories.feature_subscription_repo import FeatureSubscriptionRepository
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.security.backup_code_encryption import BackupCodeEncryption
from app.core.security.tenant_scope import unscoped


@click.command()
@click.option("--name", required=True, help="Organisation name")
@click.option("--email", required=True, help="Admin user email")
@click.option("--password", required=True, help="Admin user password")
def create_org(name, email, password):
    """Create a new organisation with an admin user"""
    db = db_session()
    try:
        # Creating a brand-new org's first admin user: there is no ambient tenant context to
        # check against (this call establishes the tenant), and this CLI never runs inside a
        # Flask request context. Explicit, not just fail-open silence.
        org, user, _ = ops.create_organisation(db, name=name, admin_email=email, password=password, actor=ops.CLI_ACTOR)

        click.echo(f"✅ Created organisation: {org.name} (ID: {org.id})")
        click.echo(f"✅ Created admin user: {user.email} (ID: {user.id})")
    except ValueError as e:
        click.echo(f"❌ Error: {e}", err=True)
    except Exception as e:
        click.echo(f"❌ Failed to create organisation: {e}", err=True)
        db.rollback()
    finally:
        db.close()


@click.command()
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--email", required=True, help="User email")
@click.option("--password", required=True, help="User password")
@click.option("--role", default="member", type=click.Choice(["admin", "member"]), help="User role")
def create_user(org_id, email, password, role):
    """Create a new user in an organisation"""
    try:
        org_uuid = UUID(org_id)
    except ValueError:
        click.echo(f"❌ Invalid organisation ID: {org_id}", err=True)
        return

    db = db_session()
    try:
        # Admin command targets an arbitrary org via --org-id, not the caller's own tenant --
        # there is no ambient tenant context here to check against anyway (no Flask request).
        user, _ = ops.create_user(db, org_uuid, email=email, role=role, password=password, actor=ops.CLI_ACTOR)
        click.echo(f"✅ Created user: {user.email} (ID: {user.id}, Role: {user.role.value})")
    except ops.AdminOperationError as e:
        click.echo(f"❌ {e}", err=True)
        db.rollback()
    except Exception as e:
        click.echo(f"❌ Failed to create user: {e}", err=True)
        db.rollback()
    finally:
        db.close()


@click.command(name="reset-password")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--email", required=True, help="User email")
@click.option("--password", required=True, help="New password")
def reset_password(org_id, email, password):
    """Reset an existing user's password.

    There is no self-service "forgot password" email flow in this app, and create-user
    refuses to touch an email that already exists -- this is the only way to recover an
    admin account whose password is lost. Also clears any lockout, same as the
    `password_reset` login flag's unlock behaviour, so a lost password and a locked
    account don't require two separate recovery steps.
    """
    try:
        org_uuid = UUID(org_id)
    except ValueError:
        click.echo(f"❌ Invalid organisation ID: {org_id}", err=True)
        return

    db = db_session()
    try:
        # Admin command targets an arbitrary org via --org-id, same reasoning as create_user.
        user, _ = ops.reset_password(db, org_uuid, email=email, password=password, actor=ops.CLI_ACTOR)
        click.echo(f"✅ Password reset for {user.email} (ID: {user.id})")
    except ops.AdminOperationError as e:
        click.echo(f"❌ {e}", err=True)
        db.rollback()
    except Exception as e:
        click.echo(f"❌ Failed to reset password: {e}", err=True)
        db.rollback()
    finally:
        db.close()


@click.command()
@click.option("--status", type=click.Choice(["active", "suspended", "all"]), default="all", help="Filter by status")
def list_orgs(status):
    """List all organisations"""
    db = db_session()
    try:
        # Lists across every org by design -- explicit for consistency with the other admin
        # commands, though Organisation itself carries no org_id to filter on.
        with unscoped():
            org_repo = OrganisationRepository(db)

            if status == "all":
                orgs = org_repo.list_orgs()
            else:
                org_status = OrganisationStatus.ACTIVE if status == "active" else OrganisationStatus.SUSPENDED
                orgs = org_repo.list_orgs(status=org_status)

        if not orgs:
            click.echo("No organisations found")
            return

        click.echo(f"\nFound {len(orgs)} organisation(s):\n")
        for org in orgs:
            click.echo(f"  ID: {org.id}")
            click.echo(f"  Name: {org.name}")
            click.echo(f"  Status: {org.status.value}")
            click.echo(f"  Created: {org.created_at}")
            click.echo()
    except Exception as e:
        click.echo(f"❌ Failed to list organisations: {e}", err=True)
    finally:
        db.close()


@click.command()
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--active-only", is_flag=True, help="Show only active users")
def list_users(org_id, active_only):
    """List users in an organisation"""
    try:
        org_uuid = UUID(org_id)
    except ValueError:
        click.echo(f"❌ Invalid organisation ID: {org_id}", err=True)
        return

    db = db_session()
    try:
        # Admin command targets an arbitrary org via --org-id, same reasoning as create_user.
        with unscoped():
            user_repo = UserRepository(db)
            users = user_repo.list_users_for_org(org_uuid, active_only=active_only)

        if not users:
            click.echo("No users found")
            return

        click.echo(f"\nFound {len(users)} user(s):\n")
        for user in users:
            status = "✅ Active" if user.is_active else "❌ Inactive"
            click.echo(f"  ID: {user.id}")
            click.echo(f"  Email: {user.email}")
            click.echo(f"  Role: {user.role.value}")
            click.echo(f"  Status: {status}")
            click.echo(f"  Created: {user.created_at}")
            click.echo()
    except Exception as e:
        click.echo(f"❌ Failed to list users: {e}", err=True)
    finally:
        db.close()


@click.command()
@click.option("--user-id", required=True, help="User ID to retrieve backup codes for")
def get_backup_codes(user_id):
    """Retrieve and decrypt 2FA backup codes for a user (admin only)

    WARNING: This command decrypts and displays backup codes.
    Use only when a user is locked out and needs admin intervention.
    """
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        click.echo(f"❌ Invalid user ID: {user_id}", err=True)
        return

    db = db_session()
    try:
        # Admin command targets an arbitrary user by ID, any org -- no ambient tenant context
        # here to check against anyway (no Flask request).
        with unscoped():
            user_repo = UserRepository(db)
            user = user_repo.get_user_by_id(user_uuid)

            if not user:
                click.echo(f"❌ User not found: {user_id}", err=True)
                return

            if not user.two_factor_enabled:
                click.echo(f"❌ User {user.email} does not have 2FA enabled", err=True)
                return

            # Get backup codes
            encryption = BackupCodeEncryption()
            backup_code_repo = BackupCodeRepository(db, encryption)
            backup_codes = backup_code_repo.get_all_codes_for_user(user_uuid)

        if not backup_codes:
            click.echo(f"❌ No backup codes found for user {user.email}", err=True)
            return

        click.echo(f"\n🔐 Backup codes for user: {user.email} (ID: {user_id})\n")
        click.echo("⚠️  WARNING: These codes are sensitive. Handle with care!\n")

        unconsumed_count = 0
        consumed_count = 0

        for backup_code in backup_codes:
            try:
                decrypted_code = encryption.decrypt(backup_code.encrypted_code)
                status = "✅ Available" if not backup_code.consumed else "❌ Used"
                click.echo(f"  {decrypted_code} - {status}")

                if backup_code.consumed:
                    consumed_count += 1
                else:
                    unconsumed_count += 1
            except Exception as e:
                click.echo(f"  ❌ Failed to decrypt code (ID: {backup_code.id}): {e}", err=True)

        click.echo("\n📊 Summary:")
        click.echo(f"  Total codes: {len(backup_codes)}")
        click.echo(f"  Available: {unconsumed_count}")
        click.echo(f"  Used: {consumed_count}")
        click.echo()

    except Exception as e:
        click.echo(f"❌ Failed to retrieve backup codes: {e}", err=True)
        db.rollback()
    finally:
        db.close()


def _resolve_org(db, org_id: str):
    """Return an Organisation for a --org-id value, or None (after echoing an error)."""
    try:
        org_uuid = UUID(org_id)
    except ValueError:
        click.echo(f"❌ Invalid organisation ID: {org_id}", err=True)
        return None
    org = OrganisationRepository(db).get_org_by_id(org_uuid)
    if org is None:
        click.echo(f"❌ Organisation not found: {org_id}", err=True)
        return None
    return org


@click.command(name="grant-feature")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--feature", required=True, help="Feature key, e.g. 'compliant'")
@click.option("--note", default=None, help="Optional note recorded on the grant")
def grant_feature(org_id, feature, note):
    """Grant (or re-activate) a per-org feature subscription. Idempotent."""
    db = db_session()
    try:
        with unscoped():
            org = _resolve_org(db, org_id)
            if org is None:
                raise SystemExit(1)
        row = ops.grant_feature(db, org.id, feature, note=note, actor=ops.CLI_ACTOR)
        click.echo(f"✅ {org.name}: feature '{row.feature_key}' active (granted {row.granted_at:%Y-%m-%d %H:%M})")
    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"❌ Failed to grant feature: {e}", err=True)
        db.rollback()
        raise SystemExit(1) from e
    finally:
        db.close()


@click.command(name="revoke-feature")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--feature", required=True, help="Feature key, e.g. 'compliant'")
def revoke_feature(org_id, feature):
    """Deactivate a per-org feature subscription."""
    db = db_session()
    try:
        with unscoped():
            org = _resolve_org(db, org_id)
            if org is None:
                raise SystemExit(1)
        changed = ops.revoke_feature(db, org.id, feature, actor=ops.CLI_ACTOR)
        if changed:
            click.echo(f"✅ {org.name}: feature '{feature}' revoked")
        else:
            click.echo(f"ℹ️  {org.name}: no '{feature}' subscription to revoke")
    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"❌ Failed to revoke feature: {e}", err=True)
        db.rollback()
        raise SystemExit(1) from e
    finally:
        db.close()


@click.command(name="list-features")
@click.option("--org-id", required=True, help="Organisation ID")
def list_features(org_id):
    """List a single organisation's feature subscriptions."""
    db = db_session()
    try:
        with unscoped():
            org = _resolve_org(db, org_id)
            if org is None:
                raise SystemExit(1)
            rows = FeatureSubscriptionRepository(db).list_for_org(org.id)
        if not rows:
            click.echo(f"{org.name}: no feature subscriptions")
            return
        click.echo(f"\n{org.name} feature subscriptions:\n")
        for row in rows:
            state = "✅ active" if row.active else "❌ inactive"
            click.echo(f"  {row.feature_key:<20} {state:<12} granted {row.granted_at:%Y-%m-%d %H:%M}")
        click.echo()
    except SystemExit:
        raise
    except Exception as e:
        click.echo(f"❌ Failed to list features: {e}", err=True)
        raise SystemExit(1) from e
    finally:
        db.close()
