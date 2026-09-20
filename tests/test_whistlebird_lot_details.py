"""Lot-detail replay writes must be supported by a particular lot's history."""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import whistlebird_lot_details as lots  # noqa: E402


def test_production_lot_code_includes_the_unique_production_batch():
    assert lots.production_lot_code("VAT56", "6") == "6 (VAT56)"
    assert lots.production_lot_code("VAT56", None) == "VAT56"
    assert lots.production_lot_code(None, "6") == "6"


def test_raw_lot_links_only_to_processes_that_consumed_that_specific_lot():
    item_id = uuid4()
    consumed_process = uuid4()

    assert lots._linked_processes(item_id, {item_id: {consumed_process: "Wildflower gin"}}) == (
        (consumed_process, "Wildflower gin"),
    )
    assert lots._linked_processes(item_id, {}) == ()
