"""Rough site capacity observation from pinned workflow timing snapshots.

Calendar-day minutes are an approximation. This service does not reserve a
resource, approve a batch start, or produce a trustworthy delivery promise.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from uuid import UUID

from app.core.db.models.organisation import Organisation
from app.core.db.models.site import Site
from app.core.db.models.step import Step
from app.features.planning.batch_models import PlanningBatch
from app.features.planning.capacity_models import PlanningCapacitySetting


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Choose a valid capacity record ID") from exc


def _whole(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be a whole number from {low} to {high}")
    return value


def _calendar(group):
    working = group.get("working_days", list(range(7)))
    closed = group.get("closed_dates", [])
    if (
        not isinstance(working, list)
        or len(working) > 7
        or any(type(day) is not int or not 0 <= day <= 6 for day in working)
        or len(set(working)) != len(working)
    ):
        raise ValueError("Working days must be distinct weekdays from Monday (0) to Sunday (6)")
    if not isinstance(closed, list) or len(closed) > 366:
        raise ValueError("Use at most 366 closed dates")
    normalized = []
    for value in closed:
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Closed dates must be YYYY-MM-DD") from exc
        if parsed.isoformat() != value or value in normalized:
            raise ValueError("Closed dates must be distinct dates in YYYY-MM-DD format")
        normalized.append(value)
    return sorted(working), sorted(normalized)


def save_setting(db, org_id, site_id, data):
    """Replace a site's named groups and assignments with optimistic revision."""
    if not isinstance(data, dict) or set(data) != {"groups", "assignments", "expected_revision"}:
        raise ValueError("Expected groups, assignments and revision")
    site_id = _uuid(site_id)
    org = db.query(Organisation).filter(Organisation.id == org_id).with_for_update().one_or_none()
    site = (
        db.query(Site)
        .filter(Site.org_id == org_id, Site.id == site_id, Site.is_active.is_(True))
        .with_for_update(read=True)
        .one_or_none()
    )
    if org is None or site is None or (not org.multiple_sites_enabled and not site.is_default):
        raise ValueError("Choose an active planning site belonging to this business")
    groups, assignments = data["groups"], data["assignments"]
    if not isinstance(groups, list) or len(groups) > 20 or not isinstance(assignments, list) or len(assignments) > 200:
        raise ValueError("Use at most 20 resource groups and 200 step assignments")
    clean_groups, group_ids, names = [], set(), set()
    for group in groups:
        required = {"id", "name", "minutes_per_day"}
        if (
            not isinstance(group, dict)
            or not required <= set(group)
            or set(group) - required - {"working_days", "closed_dates"}
        ):
            raise ValueError("Resource groups need ID, name and daily minutes")
        group_id = str(_uuid(group["id"]))
        name = group["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Resource group name must be 1 to 100 characters")
        name = name.strip()
        if group_id in group_ids or name.casefold() in names:
            raise ValueError("Resource groups must be distinct")
        group_ids.add(group_id)
        names.add(name.casefold())
        working_days, closed_dates = _calendar(group)
        clean_groups.append(
            {
                "id": group_id,
                "name": name,
                "minutes_per_day": _whole(group["minutes_per_day"], 1, 1440, "Daily capacity"),
                "working_days": working_days,
                "closed_dates": closed_dates,
            }
        )
    clean_assignments, step_ids = [], set()
    for assignment in assignments:
        if not isinstance(assignment, dict) or set(assignment) != {"step_id", "group_id"}:
            raise ValueError("Step assignments need a step and resource group")
        step_id, group_id = str(_uuid(assignment["step_id"])), str(_uuid(assignment["group_id"]))
        if step_id in step_ids or group_id not in group_ids:
            raise ValueError("Each step may use one registered group at this site")
        step_ids.add(step_id)
        clean_assignments.append({"step_id": step_id, "group_id": group_id})
    if step_ids:
        existing = {
            str(step.id)
            for step in db.query(Step.id)
            .filter(Step.org_id == org_id, Step.id.in_([UUID(value) for value in step_ids]))
            .all()
        }
        if existing != step_ids:
            raise ValueError("Step assignments must belong to this business")
    row = (
        db.query(PlanningCapacitySetting)
        .filter(PlanningCapacitySetting.org_id == org_id, PlanningCapacitySetting.site_id == site_id)
        .with_for_update()
        .one_or_none()
    )
    expected = _whole(data["expected_revision"], 0, 1_000_000, "Expected revision")
    if expected != (row.revision if row else 0):
        raise ValueError("Capacity settings changed; reload before saving")
    if row is None:
        row = PlanningCapacitySetting(org_id=org_id, site_id=site_id, revision=1, config={})
        db.add(row)
    else:
        row.revision += 1
    row.config = {"groups": clean_groups, "assignments": clean_assignments}
    db.flush()
    return row


def setting_dict(row):
    return {"site_id": str(row.site_id), "revision": row.revision, **row.config}


def _batch_load(batch, assignments):
    """DAG earliest-start load, with waits after a step before successors."""
    if isinstance(batch.snapshot, dict) and batch.snapshot.get("readiness_reasons"):
        raise ValueError("Workflow has an unknown ready date; capacity timing needs review")
    rows = batch.snapshot.get("steps") if isinstance(batch.snapshot, dict) else None
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Workflow timing snapshot is unresolved")
    steps = {row.get("step_id"): row for row in rows if isinstance(row, dict)}
    if len(steps) != len(rows):
        raise ValueError("Workflow timing snapshot is unresolved")
    finished, visiting, spans = {}, set(), []
    origin = datetime.combine(batch.proposed_start_date, time.min)

    def visit(step_id):
        if step_id in finished:
            return finished[step_id]
        if step_id in visiting or step_id not in steps:
            raise ValueError("Workflow timing dependencies are unresolved")
        visiting.add(step_id)
        step = steps[step_id]
        predecessors = step.get("predecessors")
        if not isinstance(predecessors, list):
            raise ValueError("Workflow timing dependencies are unresolved")
        start = max((visit(predecessor) for predecessor in predecessors), default=origin)
        duration = _whole(step.get("duration_minutes"), 0, 525_600, "Step duration")
        waiting = _whole(step.get("waiting_minutes"), 0, 525_600, "Step wait")
        ready = _whole(step.get("readiness_seconds"), 0, 31_536_000, "Step readiness")
        stop = start + timedelta(minutes=duration)
        if step_id in assignments and duration:
            spans.append((assignments[step_id], start, stop))
        finished[step_id] = stop + timedelta(minutes=waiting, seconds=ready)
        visiting.remove(step_id)
        return finished[step_id]

    for step_id in steps:
        visit(step_id)
    return spans, set(steps) - set(assignments)


def review(db, org_id, start, end):
    """Observed day loads only; incomplete settings are made explicit per batch."""
    if type(start) is not date or type(end) is not date or end < start or (end - start).days > 30 or end.year >= 9999:
        raise ValueError("Choose one to 31 calendar days")
    settings = (
        db.query(PlanningCapacitySetting)
        .filter(PlanningCapacitySetting.org_id == org_id)
        .order_by(PlanningCapacitySetting.site_id)
        .all()
    )
    sites = (
        db.query(Site)
        .filter(Site.org_id == org_id, Site.is_active.is_(True))
        .order_by(Site.is_default.desc(), Site.name)
        .all()
    )
    by_site = {row.site_id: row for row in settings}
    batches = (
        db.query(PlanningBatch)
        .filter(
            PlanningBatch.org_id == org_id,
            PlanningBatch.status.in_(("planned", "blocked")),
            PlanningBatch.proposed_start_date <= end,
        )
        .order_by(PlanningBatch.proposed_start_date, PlanningBatch.id)
        .limit(1001)
        .all()
    )
    if len(batches) > 1000:
        raise ValueError("Too many batches to review; choose a shorter period")
    loads, unresolved = defaultdict(lambda: {"minutes": 0, "batches": []}), []
    for batch in batches:
        config = by_site.get(batch.site_id)
        if config is None:
            unresolved.append({"batch_id": str(batch.id), "reason": "Site resource groups are not configured"})
            continue
        assignments = {item["step_id"]: item["group_id"] for item in config.config["assignments"]}
        try:
            spans, missing = _batch_load(batch, assignments)
        except (ValueError, TypeError, OverflowError, KeyError) as exc:
            unresolved.append({"batch_id": str(batch.id), "reason": str(exc)})
            continue
        if missing:
            unresolved.append(
                {"batch_id": str(batch.id), "reason": f"{len(missing)} workflow step(s) lack a resource group"}
            )
        for group_id, step_start, step_stop in spans:
            cursor = max(step_start, datetime.combine(start, time.min))
            boundary = min(step_stop, datetime.combine(end + timedelta(days=1), time.min))
            while cursor < boundary:
                next_day = datetime.combine(cursor.date() + timedelta(days=1), time.min)
                minutes = int((min(next_day, boundary) - cursor).total_seconds() // 60)
                key = (str(batch.site_id), group_id, cursor.date().isoformat())
                loads[key]["minutes"] += minutes
                loads[key]["batches"].append(
                    {
                        "batch_id": str(batch.id),
                        "minutes": minutes,
                        "priority": batch.priority,
                        "pinned": batch.pinned,
                        "proposed_start_date": batch.proposed_start_date.isoformat(),
                    }
                )
                cursor = min(next_day, boundary)
    days = []
    for setting in settings:
        for group in setting.config["groups"]:
            working_days, closed_dates = _calendar(group)
            for offset in range((end - start).days + 1):
                calendar_day = start + timedelta(days=offset)
                day = calendar_day.isoformat()
                load = loads.get((str(setting.site_id), group["id"], day), {"minutes": 0, "batches": []})
                if not load["minutes"]:
                    continue
                closed = calendar_day.weekday() not in working_days or day in closed_dates
                capacity = 0 if closed else group["minutes_per_day"]
                overloaded = load["minutes"] > capacity
                movable = sorted(
                    (item for item in load["batches"] if not item["pinned"]),
                    key=lambda item: (item["priority"], item["batch_id"]),
                )
                days.append(
                    {
                        "site_id": str(setting.site_id),
                        "group_id": group["id"],
                        "group_name": group["name"],
                        "day": day,
                        "load_minutes": load["minutes"],
                        "capacity_minutes": capacity,
                        "calendar_closed": closed,
                        "overloaded": overloaded,
                        "batches": load["batches"],
                        "suggest_move_batch_id": movable[0]["batch_id"] if overloaded and movable else None,
                        "suggest_move_start_date": movable[0]["proposed_start_date"]
                        if overloaded and movable
                        else None,
                    }
                )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sites": [{"id": str(site.id), "name": site.name} for site in sites],
        "settings": [setting_dict(row) for row in settings],
        "days": days,
        "unresolved": unresolved,
        "complete_capacity_clearance": False,
        "forecast_ready_date": None,
        "reservations_created": False,
    }
