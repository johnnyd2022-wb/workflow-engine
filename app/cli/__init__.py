"""Main CLI entry point using Click"""

import click

from . import admin, api, lint, migrations


@click.group()
def cli():
    """Workflow Engine CLI - Entry point for all commands"""
    pass


# Register subcommands
cli.add_command(api.start)
cli.add_command(api.serve)
cli.add_command(migrations.migrate)
cli.add_command(migrations.init_db)
cli.add_command(migrations.upgrade_db)
cli.add_command(admin.create_org)
cli.add_command(admin.create_user)
cli.add_command(admin.list_orgs)
cli.add_command(admin.list_users)
cli.add_command(admin.get_backup_codes)
cli.add_command(lint.lint, name="lint")
cli.add_command(lint.format_code, name="format")
cli.add_command(lint.fix_all, name="fix-all")

if __name__ == "__main__":
    cli()
