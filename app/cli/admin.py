"""Admin CLI commands for organisations and users"""

import click
from uuid import UUID

from app.core.db import db_session, engine
from app.core.db.models.models import Base
from app.core.db.repositories.organisation_repo import OrganisationRepository
from app.core.db.repositories.user_repo import UserRepository
from app.core.db.models.organisation import OrganisationStatus
from app.core.db.models.user import UserRole
from app.core.security.auth_service import AuthService
from app.core.security.org_manager import OrgManager


@click.command()
@click.option("--name", required=True, help="Organisation name")
@click.option("--email", required=True, help="Admin user email")
@click.option("--password", required=True, help="Admin user password")
def create_org(name, email, password):
    """Create a new organisation with an admin user"""
    db = db_session()
    try:
        org_manager = OrgManager(db)
        org, user = org_manager.create_org_with_admin_user(name, email, password)

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
        user_repo = UserRepository(db)
        auth_service = AuthService(db)

        # Check if user already exists
        existing_user = user_repo.get_user_by_email(email)
        if existing_user:
            click.echo(f"❌ User with email '{email}' already exists", err=True)
            return

        # Create user
        password_hash = auth_service.hash_password(password)
        user_role = UserRole.ADMIN if role == "admin" else UserRole.MEMBER
        user = user_repo.create_user(
            org_id=org_uuid,
            email=email,
            password_hash=password_hash,
            role=user_role,
            is_active=True
        )

        click.echo(f"✅ Created user: {user.email} (ID: {user.id}, Role: {user.role.value})")
    except Exception as e:
        click.echo(f"❌ Failed to create user: {e}", err=True)
        db.rollback()
    finally:
        db.close()


@click.command()
@click.option("--status", type=click.Choice(["active", "suspended", "all"]), default="all", help="Filter by status")
def list_orgs(status):
    """List all organisations"""
    db = db_session()
    try:
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

