"""Main CLI entry point using Click"""

import click

from . import admin, api, lint, maintenance, migrations, observability, operational_cases


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
cli.add_command(admin.reset_password)
cli.add_command(admin.list_orgs)
cli.add_command(admin.list_users)
cli.add_command(admin.get_backup_codes)
cli.add_command(admin.grant_feature)
cli.add_command(admin.revoke_feature)
cli.add_command(admin.list_features)
cli.add_command(admin.find_user)
cli.add_command(admin.invite_user)
cli.add_command(admin.reissue_invite)
cli.add_command(admin.set_role)
cli.add_command(admin.deactivate_user)
cli.add_command(admin.reactivate_user)
cli.add_command(admin.unlock_user)
cli.add_command(admin.change_email)
cli.add_command(admin.reset_2fa)
cli.add_command(admin.rename_org)
cli.add_command(admin.suspend_org)
cli.add_command(admin.reactivate_org)
cli.add_command(admin.org_history)
cli.add_command(admin.set_access_expiry)
cli.add_command(admin.unlink_google)
cli.add_command(admin.forget_devices)
cli.add_command(admin.disconnect_xero)
cli.add_command(admin.needs_attention)
cli.add_command(lint.lint, name="lint")
cli.add_command(lint.format_code, name="format")
cli.add_command(lint.fix_all, name="fix-all")
cli.add_command(observability.observability)
cli.add_command(maintenance.warm_system_findings)
cli.add_command(operational_cases.export_operational_cases, name="operational-cases-export")
cli.add_command(operational_cases.rehearse_operational_cases, name="operational-cases-rehearse")

if __name__ == "__main__":
    cli()
