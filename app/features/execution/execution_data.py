"""Separate user prompt values from system-owned execution trace fields."""

EXECUTION_DATA_TRACE_KEYS = {
    "completed_by",
    "completed_by_email",
    "completed_by_user_id",
    "completed_at",
    "entered_at",
    "execution_errors",
    "execution_warnings",
}


def _to_iso_timestamp(ts) -> str | None:
    """Normalize a timestamp to ISO format string for consistent API output."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def split_execution_data(execution_data: dict | None, completed_at=None):
    """
    Split execution_data into user prompts and system trace. Single place for prompt/trace split logic.
    Returns (prompts_dict, trace_dict). Use for extra_data.execution_prompts and extra_data.execution_trace.

    Audit keys (completed_by, completed_by_email, …) are mirrored from persisted execution_data. For HTTP step
    completion, ``_strip_incoming_execution_trace_keys`` drops client-supplied trace keys before merge; identity is
    then set from the authenticated session. Other persistence paths must enforce the same contract.
    """
    if not execution_data:
        return {}, {}
    prompts = {
        k: v for k, v in execution_data.items() if k not in EXECUTION_DATA_TRACE_KEYS and v is not None and v != ""
    }
    trace = {}
    for key in ("completed_by", "completed_by_email"):
        if execution_data.get(key) is not None:
            trace[key] = execution_data[key]
    completed_ts = execution_data.get("completed_at")
    if completed_ts is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_ts)
    elif completed_at is not None:
        trace["completed_at"] = _to_iso_timestamp(completed_at)
    if execution_data.get("entered_at") is not None:
        trace["entered_at"] = _to_iso_timestamp(execution_data["entered_at"])
    for key in ("execution_errors", "execution_warnings"):
        if execution_data.get(key) is not None:
            trace[key] = execution_data[key]
    return prompts, trace
