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


# ── Support commands ───────────────────────────────────────────────────────────
# Each is one call into app.admin_site.operations, the code behind the same button on
# the admin site, so a change made here is audited (as `cli`) and behaves identically.


def _run(operation, describe):
    """Run one admin operation, print its outcome, and exit non-zero if it was refused."""
    db = db_session()
    try:
        click.echo(f"✅ {describe(operation(db))}")
    except ops.AdminOperationError as e:
        db.rollback()
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1) from e
    finally:
        db.close()


def _person_options(command):
    command = click.option("--user-id", required=True, help="User ID (see find-user)")(command)
    return click.option("--org-id", required=True, help="Organisation ID")(command)


@click.command(name="find-user")
@click.option("--email", required=True, help="Email, or part of one (at least 3 characters)")
def find_user(email):
    """Find people by email across every organisation."""
    db = db_session()
    try:
        results = ops.find_people(db, email)
        if not results:
            click.echo("No users found")
            return
        for user, org in results:
            state = "active" if user.is_active else ("invited" if user.invite_token_hash else "inactive")
            click.echo(f"  {user.email}  {user.role.value}  {state}  2FA {'on' if user.two_factor_enabled else 'off'}")
            click.echo(f"    user {user.id}  org {org.id} ({org.name}, {org.status.value})")
    finally:
        db.close()


@click.command(name="invite-user")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--email", required=True, help="User email")
@click.option("--role", default="member", type=click.Choice(["admin", "member"]), help="User role")
def invite_user(org_id, email, role):
    """Add a person who chooses their own password; prints a one-time setup token."""
    _run(
        lambda db: ops.create_user(db, org_id, email=email, role=role, actor=ops.CLI_ACTOR),
        lambda result: f"Invited {result[0].email}. Setup link (valid 7 days): <app URL>/invite/{result[1]}",
    )


@click.command(name="reissue-invite")
@_person_options
def reissue_invite(org_id, user_id):
    """A new setup token for someone who has not accepted yet; the old one stops working."""
    _run(
        lambda db: ops.reissue_invite(db, org_id, user_id, actor=ops.CLI_ACTOR),
        lambda result: f"New setup link for {result[0].email}: <app URL>/invite/{result[1]}",
    )


@click.command(name="set-role")
@_person_options
@click.option("--role", required=True, type=click.Choice(["admin", "member"]))
def set_role(org_id, user_id, role):
    """Make someone an admin or a member."""
    _run(
        lambda db: ops.set_user_role(db, org_id, user_id, role, actor=ops.CLI_ACTOR),
        lambda user: f"{user.email} is now {user.role.value}",
    )


@click.command(name="deactivate-user")
@_person_options
def deactivate_user(org_id, user_id):
    """Stop someone signing in. Nothing is deleted."""
    _run(
        lambda db: ops.set_user_active(db, org_id, user_id, False, actor=ops.CLI_ACTOR),
        lambda user: f"{user.email} deactivated",
    )


@click.command(name="reactivate-user")
@_person_options
def reactivate_user(org_id, user_id):
    """Let a deactivated person sign in again."""
    _run(
        lambda db: ops.set_user_active(db, org_id, user_id, True, actor=ops.CLI_ACTOR),
        lambda user: f"{user.email} reactivated",
    )


@click.command(name="unlock-user")
@_person_options
def unlock_user(org_id, user_id):
    """Clear a sign-in lockout without changing the password."""
    _run(
        lambda db: ops.unlock_user(db, org_id, user_id, actor=ops.CLI_ACTOR),
        lambda user: f"{user.email} unlocked",
    )


@click.command(name="change-email")
@_person_options
@click.option("--email", required=True, help="New email address")
def change_email(org_id, user_id, email):
    """Change the address someone signs in with."""
    _run(
        lambda db: ops.change_user_email(db, org_id, user_id, email, actor=ops.CLI_ACTOR),
        lambda user: f"Email changed to {user.email}",
    )


@click.command(name="reset-2fa")
@_person_options
def reset_2fa(org_id, user_id):
    """Switch 2FA off for someone who lost their authenticator (also removes their backup
    codes and remembered devices)."""
    _run(
        lambda db: ops.reset_two_factor(db, org_id, user_id, actor=ops.CLI_ACTOR),
        lambda user: f"2FA switched off for {user.email}",
    )


@click.command(name="rename-org")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--name", required=True, help="New organisation name")
def rename_org(org_id, name):
    """Rename an organisation."""
    _run(
        lambda db: ops.rename_organisation(db, org_id, name, actor=ops.CLI_ACTOR),
        lambda org: f"Organisation renamed to {org.name}",
    )


@click.command(name="suspend-org")
@click.option("--org-id", required=True, help="Organisation ID")
def suspend_org(org_id):
    """Suspend an organisation: no one in it can sign in. Nothing is deleted."""
    _run(
        lambda db: ops.set_organisation_status(db, org_id, OrganisationStatus.SUSPENDED, actor=ops.CLI_ACTOR),
        lambda org: f"{org.name} suspended",
    )


@click.command(name="reactivate-org")
@click.option("--org-id", required=True, help="Organisation ID")
def reactivate_org(org_id):
    """Make a suspended organisation active again."""
    _run(
        lambda db: ops.set_organisation_status(db, org_id, OrganisationStatus.ACTIVE, actor=ops.CLI_ACTOR),
        lambda org: f"{org.name} is active",
    )


@click.command(name="set-access-expiry")
@_person_options
@click.option("--until", default="", help="Last day of access, YYYY-MM-DD. Omit to remove the end date.")
def set_access_expiry(org_id, user_id, until):
    """Give someone's access an end date, extend it, or remove it."""
    _run(
        lambda db: ops.set_access_expiry(db, org_id, user_id, until, actor=ops.CLI_ACTOR),
        lambda user: (
            f"{user.email} has access until {user.access_expires_at:%Y-%m-%d %H:%M %Z}"
            if user.access_expires_at
            else f"{user.email} has no access end date"
        ),
    )


@click.command(name="unlink-google")
@_person_options
def unlink_google(org_id, user_id):
    """Remove someone's Google sign-in link; they sign in with their password."""
    _run(
        lambda db: ops.unlink_google(db, org_id, user_id, actor=ops.CLI_ACTOR),
        lambda user: f"Google sign-in unlinked for {user.email}",
    )


@click.command(name="forget-devices")
@_person_options
def forget_devices(org_id, user_id):
    """Forget every browser allowed to skip 2FA for someone."""
    _run(
        lambda db: ops.forget_devices(db, org_id, user_id, actor=ops.CLI_ACTOR),
        lambda result: f"Forgot {result[1]} remembered device(s) for {result[0].email}",
    )


@click.command(name="disconnect-xero")
@click.option("--org-id", required=True, help="Organisation ID")
def disconnect_xero(org_id):
    """Drop an organisation's stuck Xero connection so they can connect again."""
    _run(
        lambda db: ops.disconnect_xero(db, org_id, actor=ops.CLI_ACTOR),
        lambda org: f"Xero disconnected for {org.name}",
    )


@click.command(name="needs-attention")
def needs_attention():
    """Who is locked out, whose invite or access has run out, and organisations with no admin."""
    db = db_session()
    try:
        attention = ops.needs_attention(db)
        titles = (("locked", "Locked out"), ("invite_expired", "Invite ran out"), ("access_expired", "Access ended"))
        for key, title in titles:
            rows, total = attention[key]
            click.echo(f"{title}: {total}")
            for user, org in rows:
                click.echo(f"  {user.email}  user {user.id}  org {org.id} ({org.name})")
        orgs, total = attention["no_admin"]
        click.echo(f"No admin who can sign in: {total}")
        for org in orgs:
            click.echo(f"  {org.name}  org {org.id}")
    finally:
        db.close()


@click.command(name="org-history")
@click.option("--org-id", required=True, help="Organisation ID")
@click.option("--user-id", default=None, help="Only this person's history")
@click.option("--limit", default=50, show_default=True, type=click.IntRange(1, 500))
def org_history(org_id, user_id, limit):
    """Recent sign-ins and changes recorded for an organisation, newest first."""
    db = db_session()
    try:
        entries, total = ops.list_audit(db, org_id, user_id=user_id, limit=limit)
        click.echo(f"{total} entries; showing {len(entries)}")
        for entry, email in entries:
            who = (entry.meta_data or {}).get("platform_admin") or email or "system"
            click.echo(f"  {entry.timestamp:%Y-%m-%d %H:%M}  {who}  {entry.action}  {entry.entity}")
    except ops.AdminOperationError as e:
        click.echo(f"❌ {e}", err=True)
        raise SystemExit(1) from e
    finally:
        db.close()
