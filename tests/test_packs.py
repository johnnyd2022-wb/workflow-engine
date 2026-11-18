"""Packs (app/core/utils/packs.py): a lot's pack lets steps use it in their own units."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.utils.packs import can_convert_for_lot, clean_pack, convert_for_lot, describe_pack, parse_pack


def lot(unit, pack=None):
    return SimpleNamespace(unit=unit, extra_data={"pack": pack} if pack else {})


@pytest.mark.parametrize(
    "text, expected",
    [
        ("24 x 200 mL", {"count": 24, "size": "200", "size_unit": "ml"}),
        ("Fever-Tree tonic 24×200ml", {"count": 24, "size": "200", "size_unit": "ml"}),
        ("700ml x 6", {"count": 6, "size": "700", "size_unit": "ml"}),
        ("Juniper 25 kg bag", {"count": 1, "size": "25", "size_unit": "kg"}),
        ("1,000 mL", {"count": 1, "size": "1000", "size_unit": "ml"}),
        ("1,5 L", {"count": 1, "size": "1.5", "size_unit": "l"}),
        ("Gin 40% 700ml", {"count": 1, "size": "700", "size_unit": "ml"}),
    ],
)
def test_parse_pack_reads_sizes_and_multipacks(text, expected):
    assert parse_pack(text) == expected


@pytest.mark.parametrize("text", ["", "Glass bottle", "650 g/L sugar syrup", "0 mL"])
def test_parse_pack_rejects_text_without_a_size(text):
    assert parse_pack(text) is None


def test_clean_pack_validates_api_input():
    assert clean_pack({"count": "6", "size": 700, "size_unit": "mL"}) == {"count": 6, "size": "700", "size_unit": "ml"}
    assert clean_pack(None) is None and clean_pack("") is None
    for bad in (
        "lots",
        {"count": 0, "size": 1, "size_unit": "ml"},
        {"count": 1, "size": "-1", "size_unit": "l"},
        {"count": 1, "size": "NaN", "size_unit": "l"},
        {"count": 1, "size": 1, "size_unit": "bottles"},
        12,
    ):
        with pytest.raises(ValueError):
            clean_pack(bad)


def test_describe_pack():
    assert describe_pack({"count": 24, "size": "200", "size_unit": "ml"}) == "24 × 200 mL"
    assert describe_pack({"count": 1, "size": "25", "size_unit": "kg"}) == "25 kg"


CASE = {"count": 24, "size": "200", "size_unit": "ml"}


def test_bottles_from_a_lot_of_cases():
    assert convert_for_lot(Decimal("12"), "bottles", lot("cases", CASE)) == Decimal("0.5000")


def test_volume_from_a_lot_of_cases():
    # 24 × 200 mL = 4.8 L a case: 2.4 L is half a case, 600 mL an eighth.
    assert convert_for_lot(Decimal("2.4"), "L", lot("cases", CASE)) == Decimal("0.5000")
    assert convert_for_lot(Decimal("600"), "ml", lot("cases", CASE)) == Decimal("0.1250")


def test_mass_from_bags():
    bag = lot("bags", {"count": 1, "size": "25", "size_unit": "kg"})
    assert convert_for_lot(Decimal("500"), "g", bag) == Decimal("0.0200")
    assert convert_for_lot(Decimal("2"), "bag", lot("bags", {"count": 1, "size": "25", "size_unit": "kg"})) == Decimal(
        "2.0000"
    )
    assert not can_convert_for_lot("bottles", lot("bags"))


def test_bottles_from_a_lot_held_in_litres():
    assert convert_for_lot(
        Decimal("6"), "bottles", lot("L", {"count": 1, "size": "700", "size_unit": "ml"})
    ) == Decimal("4.2000")


def test_ordinary_conversion_still_wins_and_ignores_the_pack():
    assert convert_for_lot(Decimal("500"), "g", lot("kg", {"count": 1, "size": "25", "size_unit": "kg"})) == Decimal(
        "0.5000"
    )
    assert convert_for_lot(Decimal("3"), "Cases", lot("cases", CASE)) == Decimal("3.0000")


def test_a_single_container_pack_does_not_turn_cases_into_bottles():
    single = lot("bottles", {"count": 1, "size": "700", "size_unit": "ml"})
    assert not can_convert_for_lot("cases", single)
    assert convert_for_lot(Decimal("1.4"), "L", single) == Decimal("2.0000")


def test_without_a_pack_incompatible_units_still_fail():
    with pytest.raises(ValueError):
        convert_for_lot(Decimal("12"), "bottles", lot("cases"))
    assert not can_convert_for_lot("L", lot("cases"))


def test_a_pack_of_the_wrong_kind_does_not_convert():
    # mass asked of a lot packed by volume
    assert not can_convert_for_lot("g", lot("cases", CASE))
    # a broken stored pack is ignored, not trusted
    assert not can_convert_for_lot("bottles", lot("cases", {"count": 0, "size": "200", "size_unit": "ml"}))


def test_settle_take_leaves_whole_containers_and_never_hides_an_over_take():
    from app.core.utils.packs import settle_take, whole_containers

    cases = lot("cases", CASE)
    one = convert_for_lot(Decimal("1"), "bottles", cases)
    assert one == Decimal("0.0417")
    # 1 case less a bottle leaves exactly 23 bottles' worth at storage precision
    assert Decimal("1") - settle_take(Decimal("1"), one, cases) == Decimal("0.9583")
    # the last bottle: 0.0417 left, 0.0417 asked, all of it taken
    assert settle_take(Decimal("0.0417"), one, cases) == Decimal("0.0417")
    # one bottle too many is still too many
    assert settle_take(Decimal("0.0417"), one * 2, cases) == one * 2
    # half a bottle open is left as is
    assert settle_take(Decimal("1"), Decimal("0.0208"), cases) == Decimal("0.0208")
    # lots without a multipack are untouched
    assert settle_take(Decimal("1"), Decimal("0.3333"), lot("kg")) == Decimal("0.3333")
    assert whole_containers(Decimal("0.9583"), cases) == 23 and whole_containers(Decimal("0.5"), lot("kg")) is None


# --- a pack with no size: a box of 500 labels ------------------------------------------------------

BOX = {"count": 500}


@pytest.mark.parametrize(
    "text, expected",
    [("500", BOX), ("500 labels", BOX), ("500 pcs", BOX), ("500 per box", BOX), ("24 bottles", {"count": 24})],
)
def test_clean_pack_reads_a_count_with_no_size(text, expected):
    assert clean_pack(text) == expected
    assert clean_pack({"count": expected["count"]}) == expected


def test_only_single_items_come_out_of_a_multipack_lot():
    cases = lot("cases", CASE)
    for other in ("pallets", "kegs", "boxes"):
        assert not can_convert_for_lot(other, cases), other  # not "one of 24 in a case"
    # nor does a pack count on a lot of bottles turn cases into bottles
    assert not can_convert_for_lot("cases", lot("bottles", {"count": 6}))


def test_settle_take_leaves_a_zero_take_alone():
    from app.core.utils.packs import settle_take

    assert settle_take(Decimal("0.0001"), Decimal("0"), lot("cases", CASE)) == Decimal("0")


@pytest.mark.parametrize(
    "text",
    [
        "1",
        "1 pcs",
        "0",
        "a few",
        "lots of labels",
        "12 oz",
        "3 lb",
        "10 gal",
        "12 ounces",
        "3 gallons",
        "2 tonnes",
        "12 fl oz",
    ],
)
def test_a_count_with_no_size_needs_more_than_one(text):
    with pytest.raises(ValueError):
        clean_pack(text)


def test_a_name_never_gives_a_count_only_pack():
    # "Labels 500" in a name is not read as a pack; only a typed pack can be a bare count
    assert parse_pack("Labels 500") is None and parse_pack("Hop pellets x 500") is None
    assert describe_pack(BOX) == "500 pcs"


def test_pieces_from_a_lot_of_boxes():
    boxes = lot("boxes", BOX)
    assert convert_for_lot(Decimal("125"), "pcs", boxes) == Decimal("0.2500")
    assert convert_for_lot(Decimal("500"), "units", boxes) == Decimal("1.0000")
    # nothing says how much a label weighs: a count pack can't stand in for grams
    assert not can_convert_for_lot("g", boxes)


def test_breakdown_prices_the_container_and_the_litre():
    from app.core.utils.packs import breakdown

    case = breakdown(Decimal("48"), lot("cases", CASE))
    assert case["pack"] == "24 × 200 mL" and case["containers"] == 24
    assert (case["per_container"], case["per_litre"], case["per_kg"]) == (Decimal("2"), Decimal("10"), None)
    # a 25 kg bag at $60: $2.40 a kg, the bag is one container
    bag = breakdown(Decimal("60"), lot("bags", {"count": 1, "size": "25", "size_unit": "kg"}))
    assert (bag["per_container"], bag["per_kg"], bag["per_litre"]) == (None, Decimal("2.4"), None)
    # held in litres, bought as 700 mL bottles: $10 a litre is $7 a bottle
    litres = breakdown(Decimal("10"), lot("L", {"count": 1, "size": "700", "size_unit": "ml"}))
    assert litres["per_container"] == Decimal("7") and litres["containers"] == 1
    boxes = breakdown(Decimal("50"), lot("boxes", BOX))
    assert boxes["per_container"] == Decimal("0.1") and boxes["per_litre"] is None and boxes["per_kg"] is None
    assert breakdown(Decimal("48"), lot("cases")) is None
    assert breakdown(None, lot("cases", CASE)) is None
