"""The NZ Customs excise guide built into the app: product types, excise items and rates.

From the Excise and Excise-equivalent Duties Table, Part A (goods manufactured in New
Zealand), and the annual indexation notices. Rates are indexed every 1 July; add the new
year's row to ``RATES`` when Customs publishes it (usually early June).

Every product type shares the same five rate bands. Three are charged per litre of
alcohol (LAL) and two per litre of the drink itself, so "duty = LAL x rate" is only right
for the per-LAL bands:

    over 1.15% to 2.5%   per litre of drink
    over 2.5% to 6%      per LAL              (and beer at any strength over 2.5%)
    over 6% to 9%        per litre of drink
    over 9% to 14%       per litre of drink   (and table wine at any strength)
    over 14%             per LAL

At 1.15% or less a drink isn't dutiable.

Customs also collects the Pae Ora (Healthy Futures) alcohol levy with each entry, in
cents per litre of drink by ABV class (``LEVY``). GST isn't charged on the Customs entry
for goods made here, but duty and levy become part of the sale price, so the GST on them
is shown as its own estimate (``GST_RATE``).

An org can still type its own rate for a tariff item on the Customs page; that wins over
this guide (see ``excise.resolve_rate``). This is a guide for estimates and drafts, not
tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

SOURCE = {
    "title": "NZ Customs Excise and Excise-equivalent Duties Table, Part A",
    "url": "https://www.customs.govt.nz/business/excise/excise-declarants/excise-items-and-duty-rates",
    "checked": "2026-10-20",
}

PER_LAL = "per_lal"
PER_LITRE = "per_litre"

# band -> (basis, [(effective_from, rate in NZD)]), oldest first. Rates exclude GST.
RATES: dict[str, tuple[str, list[tuple[date, Decimal]]]] = {
    "1.15-2.5": (
        PER_LITRE,
        [
            (date(2024, 7, 1), Decimal("0.55351")),
            (date(2025, 7, 1), Decimal("0.56747")),
            (date(2026, 7, 1), Decimal("0.58492")),
        ],
    ),
    "2.5-6": (
        PER_LAL,
        [
            (date(2024, 7, 1), Decimal("36.905")),
            (date(2025, 7, 1), Decimal("37.836")),
            (date(2026, 7, 1), Decimal("38.999")),
        ],
    ),
    "6-9": (
        PER_LITRE,
        [
            (date(2024, 7, 1), Decimal("2.9524")),
            (date(2025, 7, 1), Decimal("3.0268")),
            (date(2026, 7, 1), Decimal("3.1199")),
        ],
    ),
    "9-14": (
        PER_LITRE,
        [
            (date(2024, 7, 1), Decimal("3.6905")),
            (date(2025, 7, 1), Decimal("3.7836")),
            (date(2026, 7, 1), Decimal("3.8999")),
        ],
    ),
    "14+": (
        PER_LAL,
        [
            (date(2024, 7, 1), Decimal("67.220")),
            (date(2025, 7, 1), Decimal("68.915")),
            (date(2026, 7, 1), Decimal("71.034")),
        ],
    ),
}

NOT_DUTIABLE_MAX_ABV = Decimal("1.15")

LEVY_SOURCE = {
    "title": "NZ Customs: Pae Ora (Healthy Futures) alcohol levy rates",
    "url": "https://www.customs.govt.nz/about-us/news/important-notices/new-ministry-of-health-pae-ora-healthy-futures-alcohol-levy-rates-from-1-july-2026",
    "checked": "2026-10-20",
}

# Levy class -> (highest ABV, inclusive; None = no limit), [(effective_from, cents per litre of drink)].
LEVY: tuple[tuple[str, Decimal | None, list[tuple[date, Decimal]]], ...] = (
    (
        "A",
        Decimal("2.5"),
        [
            (date(2024, 7, 1), Decimal("0.7450")),
            (date(2025, 7, 1), Decimal("0.7890")),
            (date(2026, 7, 1), Decimal("0.8625")),
        ],
    ),
    (
        "B",
        Decimal("6"),
        [
            (date(2024, 7, 1), Decimal("2.3476")),
            (date(2025, 7, 1), Decimal("2.4471")),
            (date(2026, 7, 1), Decimal("2.6570")),
        ],
    ),
    (
        "C",
        Decimal("9"),
        [
            (date(2024, 7, 1), Decimal("3.9732")),
            (date(2025, 7, 1), Decimal("4.2078")),
            (date(2026, 7, 1), Decimal("4.6003")),
        ],
    ),
    (
        "D",
        Decimal("14"),
        [
            (date(2024, 7, 1), Decimal("4.9665")),
            (date(2025, 7, 1), Decimal("5.2597")),
            (date(2026, 7, 1), Decimal("5.7503")),
        ],
    ),
    (
        "E",
        Decimal("23"),
        [
            (date(2024, 7, 1), Decimal("8.6657")),
            (date(2025, 7, 1), Decimal("9.3323")),
            (date(2026, 7, 1), Decimal("9.5947")),
        ],
    ),
    (
        "F",
        None,
        [
            (date(2024, 7, 1), Decimal("18.5936")),
            (date(2025, 7, 1), Decimal("20.2587")),
            (date(2026, 7, 1), Decimal("21.8047")),
        ],
    ),
)

GST_RATE = Decimal("0.15")


@dataclass(frozen=True)
class Band:
    item: str  # Customs excise item number, e.g. 99.45.35A
    band: str  # key into RATES

    @property
    def basis(self) -> str:
        return RATES[self.band][0]


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    group: str
    # (highest ABV in the band, inclusive; None = no upper limit) -> Band, lowest first
    bands: tuple[tuple[Decimal | None, Band], ...]


def _single(item: str, band: str = "14+") -> tuple[tuple[None, Band]]:
    return ((None, Band(item, band)),)


def _by_strength(*items: str) -> tuple:
    """Six items for the standard ABV ladder: 2.5, 6, 9, 14, 23, above 23."""
    tops = (Decimal("2.5"), Decimal("6"), Decimal("9"), Decimal("14"), Decimal("23"), None)
    bands = ("1.15-2.5", "2.5-6", "6-9", "9-14", "14+", "14+")
    return tuple((top, Band(item, band)) for top, item, band in zip(tops, items, bands, strict=True))


CATEGORIES: tuple[Category, ...] = (
    Category("gin", "Gin", "Spirits", _single("99.45.35A")),
    Category("vodka", "Vodka", "Spirits", _single("99.45.40H")),
    Category("whisky", "Whisky", "Spirits", _single("99.45.15G")),
    Category("rum", "Rum", "Spirits", _single("99.45.30L")),
    Category("brandy", "Brandy", "Spirits", _single("99.45.10F")),
    Category("spirit_other", "Other spirit", "Spirits", _single("99.45.45J")),
    Category(
        "spirit_drink",
        "Spirit-based drink or RTD",
        "Spirit drinks",
        _by_strength("99.45.72F", "99.45.76J", "99.45.78E", "99.45.80G", "99.45.86F", "99.45.90D"),
    ),
    Category(
        "liqueur",
        "Liqueur or cordial",
        "Spirit drinks",
        _by_strength("99.50.40A", "99.50.50J", "99.50.60F", "99.50.65G", "99.50.76B", "99.50.85A"),
    ),
    Category(
        "bitters",
        "Bitters",
        "Spirit drinks",
        ((Decimal("23"), Band("99.50.10K", "14+")), (None, Band("99.50.14B", "14+"))),
    ),
    Category(
        "beer",
        "Beer",
        "Beer, wine and fermented",
        ((Decimal("2.5"), Band("99.10.25F", "1.15-2.5")), (None, Band("99.10.50G", "2.5-6"))),
    ),
    Category("wine", "Wine (grape)", "Beer, wine and fermented", _single("99.20.20L", "9-14")),
    Category(
        "wine_fortified",
        "Fortified wine",
        "Beer, wine and fermented",
        ((Decimal("14"), Band("99.20.20L", "9-14")), (None, Band("99.20.11A", "14+"))),
    ),
    Category(
        "fruit_wine",
        "Fruit or vegetable wine",
        "Beer, wine and fermented",
        (
            (Decimal("14"), Band("99.30.01K", "9-14")),
            (Decimal("23"), Band("99.30.02H", "14+")),
            (None, Band("99.30.03F", "14+")),
        ),
    ),
    Category(
        "fermented_other",
        "Cider, perry, mead or other fermented",
        "Beer, wine and fermented",
        _by_strength("99.30.21D", "99.30.26E", "99.30.32K", "99.30.47H", "99.30.59A", "99.30.62A"),
    ),
)

_BY_KEY = {c.key: c for c in CATEGORIES}
_ITEM_BANDS = {band.item: band for c in CATEGORIES for _, band in c.bands}


def category(key: str | None) -> Category | None:
    return _BY_KEY.get(key or "")


def classify(category_key: str | None, abv: Decimal | None) -> Band | None:
    """The excise item a product of this type and strength falls under; None if not dutiable or unknown."""
    cat = category(category_key)
    if cat is None or abv is None or abv <= NOT_DUTIABLE_MAX_ABV:
        return None
    for top, band in cat.bands:
        if top is None or abv <= top:
            return band
    return None


def rate_for_item(item: str | None, on: date) -> tuple[Decimal, str] | None:
    """(rate, basis) in force on ``on`` for a built-in excise item; None if unknown or before the guide starts."""
    band = _ITEM_BANDS.get((item or "").strip().upper())
    if band is None:
        return None
    basis, history = RATES[band.band]
    in_force = [rate for start, rate in history if start <= on]
    return (in_force[-1], basis) if in_force else None


def levy_rate(abv: Decimal | None, on: date) -> tuple[str, Decimal] | None:
    """(class, cents per litre of drink) of the alcohol levy on ``on``; None if not levied or before the guide starts."""
    if abv is None or abv <= NOT_DUTIABLE_MAX_ABV:
        return None
    for cls, top, history in LEVY:
        if top is None or abv <= top:
            in_force = [cents for start, cents in history if start <= on]
            return (cls, in_force[-1]) if in_force else None
    return None


def catalogue(on: date) -> list[dict]:
    """Product types for the picker, with the rate each band carries on ``on``."""
    out = []
    for c in CATEGORIES:
        bands = []
        low = NOT_DUTIABLE_MAX_ABV
        for top, band in c.bands:
            rate = rate_for_item(band.item, on)
            bands.append(
                {
                    "item": band.item,
                    "abv_above": f"{low:f}",
                    "abv_up_to": f"{top:f}" if top is not None else None,
                    "basis": band.basis,
                    "rate": f"{rate[0]:f}" if rate else None,
                }
            )
            low = top if top is not None else low
        out.append({"key": c.key, "label": c.label, "group": c.group, "bands": bands})
    return out
