"""Backward-compatible Compliant registration facade."""

from app.features.compliant.modules.nz_alcohol.module import CHECK_ID
from app.features.compliant.modules.nz_alcohol.module import run_check as run_nz_alcohol_check
from app.features.compliant.platform.registry import register_enabled_module_checks

__all__ = ["CHECK_ID", "register_compliant_checks", "run_nz_alcohol_check"]


def register_compliant_checks(runner) -> None:
    register_enabled_module_checks(runner)
