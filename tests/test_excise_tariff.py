"""The built-in NZ Customs excise guide: product types, ABV bands, rate bases and levy."""

from datetime import date
from decimal import Decimal

import pytest

from app.features.compliant.modules.nz_alcohol import excise_tariff as t


@pytest.mark.parametrize(
    ("category", "abv", "item", "basis"),
    [
        ("gin", "44", "99.45.35A", t.PER_LAL),
        ("vodka", "37.5", "99.45.40H", t.PER_LAL),
        ("beer", "2.5", "99.10.25F", t.PER_LITRE),
        ("beer", "2.51", "99.10.50G", t.PER_LAL),
        ("beer", "9", "99.10.50G", t.PER_LAL),  # beer stays per LAL above 2.5%
        ("wine", "13", "99.20.20L", t.PER_LITRE),
        ("wine", "15", "99.20.20L", t.PER_LITRE),  # unfortified wine is per litre at any strength
        ("wine_fortified", "18", "99.20.11A", t.PER_LAL),
        ("spirit_drink", "5", "99.45.76J", t.PER_LAL),
        ("spirit_drink", "7", "99.45.78E", t.PER_LITRE),
        ("spirit_drink", "14", "99.45.80G", t.PER_LITRE),
        ("spirit_drink", "14.01", "99.45.86F", t.PER_LAL),
        ("spirit_drink", "23", "99.45.86F", t.PER_LAL),
        ("spirit_drink", "23.5", "99.45.90D", t.PER_LAL),
        ("liqueur", "20", "99.50.76B", t.PER_LAL),
        ("fermented_other", "6", "99.30.26E", t.PER_LAL),
        ("fruit_wine", "12", "99.30.01K", t.PER_LITRE),
    ],
)
def test_classify_picks_the_excise_item_by_type_and_strength(category, abv, item, basis):
    band = t.classify(category, Decimal(abv))
    assert band is not None and band.item == item and band.basis == basis


def test_weak_or_unknown_products_are_not_classified():
    assert t.classify("beer", Decimal("1.15")) is None
    assert t.classify("gin", None) is None
    assert t.classify("nope", Decimal("40")) is None
    assert t.classify(None, Decimal("40")) is None


def test_rates_change_on_1_july():
    assert t.rate_for_item("99.45.35A", date(2026, 6, 30)) == (Decimal("68.915"), t.PER_LAL)
    assert t.rate_for_item("99.45.35A", date(2026, 7, 1)) == (Decimal("71.034"), t.PER_LAL)
    assert t.rate_for_item("99.45.35A", date(2024, 7, 1)) == (Decimal("67.220"), t.PER_LAL)
    assert t.rate_for_item("99.20.20L", date(2026, 9, 1)) == (Decimal("3.8999"), t.PER_LITRE)
    assert t.rate_for_item("99.45.35A", date(2024, 6, 30)) is None  # before the guide starts
    assert t.rate_for_item("2208.50.00", date(2026, 9, 1)) is None  # not a built-in item


def test_levy_is_cents_per_litre_by_class():
    assert t.levy_rate(Decimal("44"), date(2026, 9, 1)) == ("F", Decimal("21.8047"))
    assert t.levy_rate(Decimal("23"), date(2026, 9, 1)) == ("E", Decimal("9.5947"))
    assert t.levy_rate(Decimal("5"), date(2025, 9, 1)) == ("B", Decimal("2.4471"))
    assert t.levy_rate(Decimal("1"), date(2026, 9, 1)) is None


def test_catalogue_lists_every_type_with_todays_rates():
    cats = {c["key"]: c for c in t.catalogue(date(2026, 9, 1))}
    assert set(cats) == {c.key for c in t.CATEGORIES}
    assert cats["gin"]["bands"] == [
        {"item": "99.45.35A", "abv_above": "1.15", "abv_up_to": None, "basis": t.PER_LAL, "rate": "71.034"}
    ]
    assert [b["abv_up_to"] for b in cats["spirit_drink"]["bands"]] == ["2.5", "6", "9", "14", "23", None]
