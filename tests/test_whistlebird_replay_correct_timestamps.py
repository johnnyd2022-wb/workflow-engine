"""Unit tests for the replay timestamp-correction pass -- pure data in/out, no database."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_migration as wm  # noqa: E402
from whistlebird_replay_correct_timestamps import _execution_date_ranges, _marker_of  # noqa: E402
from whistlebird_replay_timeline import _green_gold_events  # noqa: E402


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
