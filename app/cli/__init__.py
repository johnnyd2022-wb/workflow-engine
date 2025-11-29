"""Main CLI entry point using Click"""

import click

from . import api, lint, migrations


@click.group()
def cli():
    """Workflow Engine CLI - Entry point for all commands"""
    pass


# Register subcommands
cli.add_command(api.start)
cli.add_command(api.serve)
cli.add_command(migrations.migrate)
cli.add_command(lint.lint, name="lint")
cli.add_command(lint.format_code, name="format")
cli.add_command(lint.fix_all, name="fix-all")

if __name__ == "__main__":
    cli()
