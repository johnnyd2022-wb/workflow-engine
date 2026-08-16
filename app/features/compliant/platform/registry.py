"""Composition seam between the Compliant platform and install-time modules.

Core imports this file only.  A module owns its framework catalogue, source versions and
domain evaluator, allowing a future industry pack to be installed without core knowing its
framework IDs or data model.
"""

from collections.abc import Callable
from typing import Protocol


class CoreCheckRegistrar(Protocol):
    def register_check(self, check_id: str, fn: Callable) -> None: ...


def register_enabled_module_checks(runner: CoreCheckRegistrar) -> None:
    """Register install-time modules in one explicit product composition root."""
    from app.features.compliant.modules.nz_alcohol.module import register_checks

    register_checks(runner)
