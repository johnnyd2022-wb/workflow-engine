"""Place batches against site capacity (GL-P07 B4).

A site's capacity setting names resource groups (minutes per working day x units) and which
workflow step uses which group. A batch's load is its steps' minutes on the days they run
(`capacity_service._batch_load`). A batch fits a start date when, on every day it touches,
each group's load from every other live batch plus this one stays within that day's capacity.

Placement keeps a batch on time when it can: the latest start on or before its planned
(backward-scheduled) start that fits, never before today. Only when nothing fits in time does
it take the earliest start after that, and the batch says it is late because of capacity.
Sites without a capacity setting, and steps no group is assigned to, are not constrained.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from app.core.db.models.execution import Execution, ExecutionStatus
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.capacity_models import PlanningCapacitySetting
from app.features.planning.capacity_service import _batch_load, day_capacity

HORIZON_DAYS = 120
LIVE_EXECUTION = (ExecutionStatus.PENDING, ExecutionStatus.IN_PROGRESS)


@dataclass
class SiteCapacity:
    groups: dict[str, dict]
    assignments: dict[str, str]
    # (group id, day) -> minutes already taken by other live batches
    load: dict[tuple[str, date], int]


def _day_minutes(spans, start: date):
    """Each (group, day) a batch starting on `start` uses, with its minutes."""
    shift = datetime.combine(start, time.min)
    minutes = defaultdict(int)
    for group_id, step_start, step_stop in spans:
        cursor, stop = shift + (step_start - datetime.min), shift + (step_stop - datetime.min)
        while cursor < stop:
            next_day = datetime.combine(cursor.date() + timedelta(days=1), time.min)
            minutes[(group_id, cursor.date())] += int((min(next_day, stop) - cursor).total_seconds() // 60)
            cursor = min(next_day, stop)
    return minutes


def spans_for(snapshot, assignments):
    """The batch's step spans relative to a start at datetime.min, or None with the reason
    when its timing can't be laid out (e.g. a ready date only known during production)."""
    probe = SimpleNamespace(snapshot=snapshot, proposed_start_date=date.min)
    try:
        spans, _ = _batch_load(probe, assignments)
    except (ValueError, TypeError, OverflowError, KeyError) as exc:
        return None, str(exc)
    return spans, None


def site_capacity(db, org_id, site_id, *, exclude_ids=()) -> SiteCapacity | None:
    """The site's groups and what every other live batch there already takes, or None when the
    site has no capacity setting (nothing to place against)."""
    if site_id is None:
        return None
    setting = (
        db.query(PlanningCapacitySetting)
        .filter(PlanningCapacitySetting.org_id == org_id, PlanningCapacitySetting.site_id == site_id)
        .one_or_none()
    )
    if setting is None or not setting.config.get("groups"):
        return None
    groups = {group["id"]: group for group in setting.config["groups"]}
    assignments = {row["step_id"]: row["group_id"] for row in setting.config["assignments"]}
    capacity = SiteCapacity(groups, assignments, defaultdict(int))
    excluded = set(exclude_ids)
    rows = (
        db.query(PlanningBatch)
        .outerjoin(Execution, (Execution.org_id == PlanningBatch.org_id) & (Execution.id == PlanningBatch.execution_id))
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.site_id == site_id,
            (PlanningBatch.status.in_(("planned", "blocked")))
            | ((PlanningBatch.status == "started") & Execution.status.in_(LIVE_EXECUTION)),
        )
        .all()
    )
    for row in rows:
        if row.id not in excluded:
            add(capacity, row.snapshot, row.proposed_start_date)
    return capacity


def add(capacity: SiteCapacity, snapshot, start: date) -> None:
    spans, _ = spans_for(snapshot, capacity.assignments)
    for key, minutes in _day_minutes(spans or [], start).items():
        capacity.load[key] += minutes


def remove(capacity: SiteCapacity, snapshot, start: date) -> None:
    spans, _ = spans_for(snapshot, capacity.assignments)
    for key, minutes in _day_minutes(spans or [], start).items():
        capacity.load[key] -= minutes


def overloads(capacity: SiteCapacity, snapshot, start: date, *, today: date):
    """[(group name, day, minutes needed, capacity)] where this batch at `start` doesn't fit,
    counting the load already in `capacity` (which must not include this batch)."""
    spans, _ = spans_for(snapshot, capacity.assignments)
    found = []
    for (group_id, day), minutes in sorted(_day_minutes(spans or [], start).items(), key=lambda item: item[0][1]):
        group = capacity.groups.get(group_id)
        if group is None or day < today:
            continue
        limit = day_capacity(group, day)
        needed = capacity.load[(group_id, day)] + minutes
        if needed > limit:
            found.append((group["name"], day, needed, limit))
    return found


def place(capacity: SiteCapacity, snapshot, preferred: date, *, today: date):
    """(start, reason). The latest start in [today, preferred] that fits, else the earliest after
    preferred within the horizon. (None, reason) when nothing fits or timing is unknown."""
    spans, problem = spans_for(snapshot, capacity.assignments)
    if spans is None:
        return None, problem
    if not spans:
        return max(preferred, today), None
    preferred = max(preferred, today)
    day = preferred
    while day >= today:
        if not overloads(capacity, snapshot, day, today=today):
            return day, None
        day -= timedelta(days=1)
    for offset in range(1, HORIZON_DAYS + 1):
        day = preferred + timedelta(days=offset)
        if not overloads(capacity, snapshot, day, today=today):
            return day, "Capacity is full until then"
    return None, f"No capacity in the next {HORIZON_DAYS} days"


def describe(problems) -> list[str]:
    return [
        f"{name} is full on {day.day} {day:%b} ({needed} of {limit} minutes)" for name, day, needed, limit in problems
    ]
