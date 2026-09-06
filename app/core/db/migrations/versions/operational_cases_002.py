"""Enforce tenant-consistent case references without rewriting existing migrations.

Revision ID: operational_cases_002
Revises: operational_cases_001
"""

from alembic import op

revision = "operational_cases_002"
down_revision = "operational_cases_001"
branch_labels = None
depends_on = None

_UNIQUES = [
    ("users", "uq_oc_users_org_id_id"),
    ("entity_events", "uq_oc_events_org_id_id"),
    ("operational_cases", "uq_operational_cases_org_id_id"),
]
_FKS = [
    ("operational_cases", "fk_oc_predecessor_org", "previous_case_id", "operational_cases", None),
    ("operational_cases", "fk_oc_owner_org", "owner_id", "users", None),
    ("operational_cases", "fk_oc_creator_org", "created_by", "users", None),
    ("operational_case_links", "fk_ocl_case_org", "case_id", "operational_cases", "CASCADE"),
    ("operational_case_links", "fk_ocl_actor_org", "created_by", "users", None),
    ("operational_case_events", "fk_oce_case_org", "case_id", "operational_cases", "CASCADE"),
    ("operational_case_events", "fk_oce_actor_org", "actor_id", "users", None),
    ("operational_case_events", "fk_oce_event_org", "entity_event_id", "entity_events", None),
]


def upgrade():
    for table, name in _UNIQUES:
        op.create_unique_constraint(name, table, ["org_id", "id"])
    for table, name, column, parent, ondelete in _FKS:
        op.create_foreign_key(name, table, parent, ["org_id", column], ["org_id", "id"], ondelete=ondelete)
    # Queue/source-status ordering stays bounded even with many terminal occurrences.
    op.create_index("ix_oc_source_recent", "operational_cases", ["org_id", "source_entity_id", "updated_at", "id"])


def downgrade():
    op.drop_index("ix_oc_source_recent", table_name="operational_cases")
    for table, name, *_ in reversed(_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, name in reversed(_UNIQUES):
        op.drop_constraint(name, table, type_="unique")
