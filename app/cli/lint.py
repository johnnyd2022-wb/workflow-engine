"""Linting and formatting CLI commands"""

import subprocess
import sys

import click


@click.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues where possible")
@click.option("--unsafe-fixes", is_flag=True, help="Enable unsafe fixes (may change code behavior)")
@click.option("--check-only", is_flag=True, help="Only check, do not fix (default)")
@click.option("--output-format", default="text", type=click.Choice(["text", "concise", "json"]), help="Output format")
def lint(fix, unsafe_fixes, check_only, output_format):
    """Run ruff linter on the codebase"""
    cmd = ["ruff", "check", "app/"]

    if fix and not check_only:
        cmd.append("--fix")
        if unsafe_fixes:
            cmd.append("--unsafe-fixes")
        click.echo("🔧 Running ruff with auto-fix enabled...")
    else:
        click.echo("🔍 Running ruff check (no auto-fix)...")

    if output_format != "text":
        cmd.extend(["--output-format", output_format])

    result = subprocess.run(cmd)

    if result.returncode == 0:
        click.echo("✅ Ruff check passed!")
        sys.exit(0)
    else:
        if not fix:
            click.echo("❌ Ruff found issues. Run with --fix to auto-fix many of them.")
            click.echo("💡 Tip: Use --unsafe-fixes to enable more aggressive fixes (review carefully)")
        else:
            click.echo("❌ Ruff found issues that could not be auto-fixed.")
        sys.exit(1)


@click.command()
@click.option("--check", is_flag=True, help="Check formatting without making changes")
def format_code(check):
    """Format code with ruff formatter"""
    cmd = ["ruff", "format"]

    if check:
        cmd.append("--check")
        click.echo("🔍 Checking code formatting...")
    else:
        click.echo("✨ Formatting code with ruff...")

    cmd.append("app/")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        if check:
            click.echo("✅ Code formatting is correct!")
        else:
            click.echo("✅ Code formatted successfully!")
        sys.exit(0)
    else:
        if check:
            click.echo("❌ Code formatting issues found. Run without --check to fix.")
        else:
            click.echo("❌ Formatting failed.")
        sys.exit(1)


@click.command()
@click.option("--unsafe-fixes", is_flag=True, help="Enable unsafe fixes (may change code behavior)")
def fix_all(unsafe_fixes):
    """Auto-fix all ruff issues and format code"""
    click.echo("🔧 Auto-fixing all ruff issues...")

    # First, try to fix linting issues
    cmd = ["ruff", "check", "--fix", "app/"]
    if unsafe_fixes:
        cmd.append("--unsafe-fixes")
    lint_result = subprocess.run(cmd)

    # Then format the code
    format_result = subprocess.run(["ruff", "format", "app/"])

    if lint_result.returncode == 0 and format_result.returncode == 0:
        click.echo("✅ All issues fixed and code formatted!")
        sys.exit(0)
    else:
        click.echo("⚠️  Some issues may remain that require manual fixing.")
        if not unsafe_fixes:
            click.echo("💡 Tip: Try with --unsafe-fixes to fix more issues (review carefully)")
        sys.exit(1)
