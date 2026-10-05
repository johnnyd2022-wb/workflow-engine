"""Unit tests for the replay timestamp-correction pass -- pure data in/out, no database."""

import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_correct_timestamps import (  # noqa: E402
    _audit_days,
    _event_times,
    _execution_date_ranges,
    _marker_of,
    _purchase_audit_days,
    _sale_event_time,
)
from whistlebird_replay_timeline import ReplayEvent, _green_gold_events  # noqa: E402


def _green_gold_record() -> wm.GreenGoldRecord:
    return wm.GreenGoldRecord(
        source_vat=53,
        source_date=date(2026, 7, 31),
        source_quantity_l=Decimal("41"),
        bottles=Decimal("144"),
        bottle_size_ml=Decimal("500"),
        batch_label="GG01",
        source_table="production_sheet",
        source_id=2035,
    )


def test_green_gold_events_resolve_to_their_execution_marker():
    """Both Green Gold events must be dated against the same execution marker the replay stamped."""
    events = _green_gold_events(_green_gold_record(), {53: "wildflower-vat53"})

    assert [_marker_of(event) for event in events] == ["green-gold-gg01", "green-gold-gg01"]


def test_green_gold_execution_gets_its_recorded_business_date_range():
    events = _green_gold_events(_green_gold_record(), {53: "wildflower-vat53"})

    assert _execution_date_ranges(events) == {"green-gold-gg01": (date(2026, 7, 31), date(2026, 7, 31))}


def test_later_recorded_purchase_moves_audit_before_its_earliest_use():
    events = [
        ReplayEvent("purchase:lot", "create_inventory_item", date(2025, 8, 1), (), {"marker": "lot"}),
        ReplayEvent("step:first", "complete_step", date(2025, 5, 3), ("purchase:lot",), {}),
        ReplayEvent("step:later", "complete_step", date(2025, 6, 1), ("purchase:lot",), {}),
    ]

    assert _purchase_audit_days(events) == {"purchase:lot": date(2025, 5, 2)}
    timestamps = _event_times(events)
    assert timestamps["purchase:lot"].astimezone(wm.DERIVED_TIMEZONE).date() == date(2025, 5, 2)
    assert timestamps["purchase:lot"] < timestamps["step:first"]
    assert _event_times(events) == timestamps


def test_same_day_purchase_keeps_recorded_date_and_precedes_use():
    events = [
        ReplayEvent("purchase:lot", "create_inventory_item", date(2025, 5, 3), (), {"marker": "lot"}),
        ReplayEvent("step:first", "complete_step", date(2025, 5, 3), ("purchase:lot",), {}),
    ]

    assert _purchase_audit_days(events) == {}
    timestamps = _event_times(events)
    assert timestamps["purchase:lot"].astimezone(wm.DERIVED_TIMEZONE).date() == date(2025, 5, 3)
    assert timestamps["purchase:lot"] < timestamps["step:first"]


def test_production_prerequisites_move_before_earlier_dated_diversion():
    events = [
        ReplayEvent("execution:base", "create_execution", date(2026, 9, 1), (), {}),
        ReplayEvent("step:base", "complete_step", date(2026, 9, 1), ("execution:base",), {}),
        ReplayEvent("execution:diversion", "create_execution", date(2026, 7, 31), ("step:base",), {}),
        ReplayEvent("step:diversion", "complete_step", date(2026, 7, 31), ("execution:diversion",), {}),
    ]

    days = _audit_days(events)
    assert days["execution:base"] == days["step:base"] == date(2026, 7, 31)
    timestamps = _event_times(events)
    assert timestamps["execution:base"] < timestamps["step:base"] < timestamps["execution:diversion"]


def test_recent_batch_dates_follow_manifest_and_only_include_recorded_steps():
    import whistlebird_recent_batches as rb
    from whistlebird_replay_correct_timestamps import _recent_batch_events

    batches = rb.parse_recent_batches_manifest(
        {
            "batches": [
                {
                    "marker": "solstice-2026-09-22-maceration",
                    "product_line": "solstice",
                    "started": "2026-09-22",
                    "steps_completed": ["maceration"],
                }
            ]
        }
    )
    events = _recent_batch_events(batches)
    assert [e.event_type for e in events] == ["create_execution", "complete_step"]
    assert {_marker_of(e) for e in events} == {batches[0].marker}
    times = _event_times(events)
    assert all(at.astimezone(wm.DERIVED_TIMEZONE).date() == date(2026, 9, 22) for at in times.values())
    assert times[events[0].event_id] < times[events[1].event_id]
    assert events[1].payload["step_index"] == 0


def test_recent_batch_later_steps_are_dated_to_the_day_they_were_done():
    """A maceration put on 22 Sept and distilled/filled on 29 Sept must not all read as the 22nd."""
    import whistlebird_recent_batches as rb
    from whistlebird_replay_correct_timestamps import _recent_batch_events

    batches = rb.parse_recent_batches_manifest(
        {
            "batches": [
                {
                    "marker": "solstice-2026-09-22-maceration",
                    "product_line": "solstice",
                    "started": "2026-09-22",
                    "steps_completed": ["maceration", "distilling", "aging"],
                    "step_dates": {"distilling": "2026-09-29", "aging": "2026-09-29"},
                    "flask_codes": ["WBSS29", "WBSS30"],
                    "vat_number": 60,
                }
            ]
        }
    )
    events = _recent_batch_events(batches)
    times = _event_times(events)
    days = [times[event.event_id].astimezone(wm.DERIVED_TIMEZONE).date() for event in events]

    assert days == [date(2026, 9, 22), date(2026, 9, 22), date(2026, 9, 29), date(2026, 9, 29)]
    assert [times[event.event_id] for event in events] == sorted(times[event.event_id] for event in events)
    assert len(set(times.values())) == 4


def test_recent_batch_with_no_recorded_steps_does_not_invent_completion():
    import whistlebird_recent_batches as rb
    from whistlebird_replay_correct_timestamps import _recent_batch_events

    batches = rb.parse_recent_batches_manifest(
        {
            "batches": [
                {
                    "marker": "started-only",
                    "product_line": "wildflower",
                    "started": "2026-09-22",
                    "steps_completed": [],
                }
            ]
        }
    )
    assert [e.event_type for e in _recent_batch_events(batches)] == ["create_execution"]


def test_timestamp_correction_refuses_other_organisations_before_connecting():
    import pytest
    from whistlebird_replay_correct_timestamps import correct_timestamps

    with pytest.raises(ValueError, match="only permitted"):
        correct_timestamps("unused", "unused", "Other tenant")


def test_synced_sale_is_dated_to_its_invoice_not_the_sync():
    """A Xero sync after a rebuild must not read as hundreds of stock actions that day."""
    now = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    made = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)

    at = _sale_event_time(date(2026, 4, 2), made, now)

    assert at == wm._derived_timestamp(date(2026, 4, 2))
    assert at.astimezone(wm.DERIVED_TIMEZONE).date() == date(2026, 4, 2)


def test_presale_is_dated_just_after_its_stock_was_made():
    now = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)
    made = datetime(2026, 5, 1, 3, 0, tzinfo=UTC)

    assert _sale_event_time(date(2026, 4, 2), made, now) == made + timedelta(seconds=1)


def test_future_dated_invoice_keeps_its_real_sync_time():
    now = datetime(2026, 10, 5, 1, 0, tzinfo=UTC)

    assert _sale_event_time(date(2026, 11, 1), None, now) is None
