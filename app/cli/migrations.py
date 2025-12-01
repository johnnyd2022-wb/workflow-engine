"""Database migration CLI commands using Alembic"""

import subprocess
import sys

import click


@click.command()
@click.option("--init", is_flag=True, help="Initialize migrations")
@click.option("--upgrade", is_flag=True, help="Run pending migrations")
@click.option("--downgrade", is_flag=True, help="Rollback last migration")
@click.option("--revision", is_flag=True, help="Create a new migration revision")
@click.option("--message", "-m", help="Migration message (use with --revision)")
@click.option("--autogenerate", is_flag=True, help="Auto-generate migration from models")
def migrate(init, upgrade, downgrade, revision, message, autogenerate):
    """Database migration commands using Alembic"""
    alembic_cmd = ["alembic"]

    if init:
        click.echo("Initializing Alembic migrations...")
        # Alembic is already initialized, just create initial migration if needed
        if revision:
            cmd = alembic_cmd + ["revision", "--autogenerate", "-m", message or "Initial migration"]
            click.echo("Creating initial migration...")
            result = subprocess.run(cmd)
            if result.returncode == 0:
                click.echo("✅ Migration revision created successfully")
            else:
                click.echo("❌ Failed to create migration revision", err=True)
                sys.exit(result.returncode)
        else:
            click.echo("✅ Alembic is already configured. Use --revision --message to create initial migration.")
    elif revision:
        if not message:
            click.echo("❌ --message is required when using --revision", err=True)
            sys.exit(1)
        if autogenerate:
            cmd = alembic_cmd + ["revision", "--autogenerate", "-m", message]
        else:
            cmd = alembic_cmd + ["revision", "-m", message]
        click.echo(f"Creating migration revision: {message}...")
        result = subprocess.run(cmd)
        if result.returncode == 0:
            click.echo("✅ Migration revision created successfully")
        else:
            click.echo("❌ Failed to create migration revision", err=True)
            sys.exit(result.returncode)
    elif upgrade:
        click.echo("Running pending migrations...")
        cmd = alembic_cmd + ["upgrade", "head"]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            click.echo("✅ Migrations applied successfully")
        else:
            click.echo("❌ Failed to apply migrations", err=True)
            sys.exit(result.returncode)
    elif downgrade:
        click.echo("Rolling back last migration...")
        cmd = alembic_cmd + ["downgrade", "-1"]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            click.echo("✅ Migration rolled back successfully")
        else:
            click.echo("❌ Failed to rollback migration", err=True)
            sys.exit(result.returncode)
    else:
        click.echo("Please specify an action: --init, --upgrade, --downgrade, or --revision")


@click.command()
def init_db():
    """Initialize database (create tables)"""
    from app.core.db import engine
    from app.core.db.models.models import Base

    click.echo("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        click.echo("✅ Database tables created successfully")
    except Exception as e:
        click.echo(f"❌ Failed to create database tables: {e}", err=True)
        sys.exit(1)


@click.command()
def upgrade_db():
    """Upgrade database to latest migration"""
    import subprocess

    click.echo("Upgrading database...")
    result = subprocess.run(["alembic", "upgrade", "head"])
    if result.returncode == 0:
        click.echo("✅ Database upgraded successfully")
    else:
        click.echo("❌ Failed to upgrade database", err=True)
        sys.exit(result.returncode)
