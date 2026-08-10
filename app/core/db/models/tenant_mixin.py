"""Shared mixin for every tenant-scoped model.

Models inherit this instead of declaring their own ``org_id = Column(...)`` — it's the single
column declaration the global filter (``app/core/db/tenant_filter.py``) binds to via
``with_loader_criteria(TenantScoped, ...)``. Any model inheriting ``TenantScoped`` gets the
global org_id filter automatically applied to every SELECT/UPDATE/DELETE that touches it,
including joins and lazy-loaded relationships (see ``tests/test_tenant_filter_spike.py`` for
the empirical proof this covers legacy Query-API calls, bulk updates, and lazy loads).

Usage: ``class Execution(TenantScoped, Base): ...`` — mixin first, ``Base`` second, the usual
SQLAlchemy declarative-mixin order.

Every model using this mixin previously declared ``org_id`` independently, with small,
apparently-unintentional variance in ``ondelete`` (some had ``ondelete="CASCADE"`` on the
Python FK object, most didn't — and for a few, e.g. ``audit_logs``/``entity_events``, the
*live* DB constraint already has ``ON DELETE CASCADE`` from an earlier migration even though
the old model never declared it, so model and DB were already out of sync before this mixin
existed). Deliberately NOT normalizing that here: ``ondelete=`` on a SQLAlchemy ``ForeignKey``
is DDL-generation metadata only — it does not change an already-applied constraint's runtime
behavior without a migration, and picking a single blanket value for every table would either
silently misdescribe the ~9 tables that are genuinely not cascading today (a real, un-migrated
behavior change smuggled into a tenant-scoping mixin) or require writing that migration as
unrequested scope creep on top of the org-scoping work this mixin exists for. Leaving
``ondelete`` unset here matches the majority baseline and is the safe drift direction if it's
wrong for a given table: DDL metadata that under-describes reality can't cause a surprise
constraint change, only an over-description could. Fixing the real inconsistency is a
candidate for the global-wins findings index, not bundled into this mixin.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declared_attr


class TenantScoped:
    """Mixin marking a model as org-scoped. Provides the org_id column; nothing else."""

    @declared_attr
    def org_id(cls):  # noqa: N805 -- declared_attr classmethod, `cls` is conventional
        return Column(
            UUID(as_uuid=True),
            ForeignKey("organisations.id"),
            nullable=False,
            index=True,
        )
