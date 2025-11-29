"""Main CLI entry point using Click"""
import click
from . import api, migrations

@click.group()
def cli():
    """Workflow Engine CLI - Entry point for all commands"""
    pass

# Register subcommands
cli.add_command(api.start)
cli.add_command(api.serve)
cli.add_command(migrations.migrate)

if __name__ == '__main__':
    cli()

