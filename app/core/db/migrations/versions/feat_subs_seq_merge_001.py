"""Merge the two alembic heads on main (entity_events_seq_001 + feature_subscriptions_001).

Revision ID: feat_subs_seq_merge_001
Revises: entity_events_seq_001, feature_subscriptions_001

Both parents branch off system_findings_cache_001:

    system_findings_cache_001
      |-- entity_events_seq_001        (feat/live-sync !196 -- adds entity_events.seq)
      `-- feature_subscriptions_001    (nz-alc-tools !198 -- adds feature_subscriptions)

Each merged to `main` independently, leaving two heads ("Multiple head revisions for
'head'"). A previous fix (3b0e4d3) rewrote feature_subscriptions_001.down_revision to
entity_events_seq_001 to linearise. That is unsafe: a migration revision is part of a
deployed database's immutable history, and changing its parent after it may have run
makes upgrade/downgrade behaviour depend on which source tree happens to be present.

This empty merge revision is the correct fix. It has no upgrade/downgrade body -- the two
branches touch different tables (entity_events vs feature_subscriptions) and are
independent, so there is nothing to reconcile; it only re-unifies the DAG to a single
head.

Deployed-state handling (production and staging alembic_version MUST be checked first):

  * fresh checkout (nothing applied)        -> plain `upgrade head` applies both branches
                                              + this merge.
  * alembic_version records BOTH heads      -> plain `upgrade head` applies this merge as
    (entity_events_seq_001 + feature_        a no-op.
     subscriptions_001)
  * alembic_version records ONLY            -> AMBIGUOUS. Check the catalog for BOTH the
    feature_subscriptions_001                    entity_events.seq column and the
                                                ix_entity_events_org_seq index:
                                                  - BOTH present -> rewritten-linear state:
                                                        alembic stamp entity_events_seq_001 \
                                                                      feature_subscriptions_001
                                                        alembic upgrade head
                                                  - BOTH absent -> this deployment genuinely
                                                    never ran the entity branch: do NOT
                                                    stamp -- plain `upgrade head` applies
                                                    entity_events_seq_001 then this merge.
                                                  - EXACTLY ONE present -> unexpected
                                                    partial/manual schema. STOP: reconcile
                                                    it by hand (finish or revert
                                                    entity_events_seq_001's effects) before
                                                    stamping or upgrading -- either action
                                                    would bless or trip over the half-state.
                                              Stamping the "both absent" case would falsely
                                              record the entity migration and leave seq /
                                              its index absent.

Any later migration must descend from feat_subs_seq_merge_001, not from either parent.
"""

from collections.abc import Sequence

revision: str = "feat_subs_seq_merge_001"
down_revision: tuple[str, ...] | str | None = ("entity_events_seq_001", "feature_subscriptions_001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
