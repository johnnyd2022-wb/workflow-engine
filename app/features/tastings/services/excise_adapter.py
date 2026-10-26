"""Frozen tasting removal adapters for legacy draft and per-CCA observations."""

from decimal import Decimal
from types import SimpleNamespace

from app.features.tastings.repositories.tasting_repo import TastingRepository


def legacy_removals(db, org_id, start, end):
    from app.features.compliant.modules.nz_alcohol.excise import Removal

    result = []
    for lot in TastingRepository(db).removals(org_id, start, end):
        fact = lot.snapshot
        item = SimpleNamespace(
            name=fact["product"],
            unit=lot.unit,
            supplier_batch_number=fact.get("batch"),
            extra_data={},
            source_execution_step_id=None,
        )
        result.append(
            Removal(
                kind="tasting",
                occurred_on=lot.removed_on,
                recorded_at=lot.created_at,
                item=item,
                quantity=lot.quantity,
                reference="tasting-stock:" + str(lot.id),
                frozen_basis=fact,
            )
        )
    return result


def add_frozen_lines(result, removals):
    """Each recorded lot retains its original rate/rounding; do not merge/reprice it."""
    entry = result["entry"]
    for removal in removals:
        fact = removal.frozen_basis
        if not fact:
            continue
        if fact.get("problems"):
            result["problems"].extend(
                {"product": fact["product"], "reason": reason, "removals": 1, "reference": removal.reference}
                for reason in fact["problems"]
            )
            continue
        line = {
            "tariff_item": fact["tariff_item"],
            "product": fact["product"],
            "units": fact["quantity"] if fact["unit"].lower() not in {"l", "ml"} else fact["litres"],
            "unit": fact["unit"] if fact["unit"].lower() not in {"l", "ml"} else "L",
            "litres": fact["litres"],
            "lal": fact["lal"],
            "rate": fact["rate"],
            "rate_per_lal": fact["rate"] if fact["rate_basis"] == "lal" else None,
            "basis": fact["rate_basis"],
            "rate_date": fact["rate_date"],
            "duty": fact["duty"],
            "removals": [
                {
                    "kind": "tasting",
                    "date": removal.occurred_on.isoformat(),
                    "reference": removal.reference,
                    "customer": None,
                    "batch": fact.get("batch"),
                    "quantity": fact["quantity"],
                    "abv_percent": fact["abv_percent"],
                    "lal": fact["lal"],
                }
            ],
        }
        result["lines"].append(line)
        result["total_lal"] = str(Decimal(result["total_lal"]) + Decimal(fact["lal"]))
        result["total_duty"] = str(Decimal(result["total_duty"]) + Decimal(fact["duty"]))
        row = {
            "line": len(entry["lines"]) + 1,
            "excise_item": fact["tariff_item"],
            "description": fact["product"],
            "units": line["units"],
            "unit": line["unit"],
            "supplementary_litres": str(Decimal(fact["litres"]).quantize(Decimal(".001"))),
            "statistical_lal": str(Decimal(fact["lal"]).quantize(Decimal(".001"))),
            "rate": fact["rate"],
            "basis": fact["rate_basis"],
            "rate_date": fact["rate_date"],
            "duty": fact["duty"],
            "levy": fact["levy"],
            "gst_on_levy": fact["gst"],
            "total": str(Decimal(fact["duty"]) + Decimal(fact["levy"]) + Decimal(fact["gst"])),
            "removal_reference": removal.reference,
        }
        entry["lines"].append(row)
        for key, source in [
            ("total_duty", "duty"),
            ("total_levy", "levy"),
            ("total_gst", "gst_on_levy"),
            ("total", "total"),
        ]:
            entry[key] = str(Decimal(entry[key]) + Decimal(row[source]))
    if result["problems"]:
        entry["complete"] = False
    return result


def add_cca_rows(db, org_id, start, end, groups, unresolved):
    for lot in TastingRepository(db).removals(org_id, start, end):
        fact = lot.snapshot
        source = fact.get("source_cca")
        identity = {"tasting_stock_lot_id": str(lot.id), "tasting_id": str(lot.tasting_id)}
        if not source or fact.get("problems"):
            unresolved.append(
                {
                    **identity,
                    "reason": "; ".join(fact.get("problems") or ["Recorded source CCA decision is unresolved"]),
                    "source_cca": source,
                }
            )
            continue
        group = groups.setdefault(
            source["id"],
            {"source_cca": dict(source), "movements": [], "observed_excise_duty": "0", "complete_lodgement": False},
        )
        group["movements"].append(
            {
                **identity,
                "occurred_on": lot.removed_on.isoformat(),
                "quantity": str(lot.quantity),
                "unit": lot.unit,
                "source_site_id": fact.get("source_site_id"),
                "treatment": "recorded_tasting_home_consumption",
                "removal_basis": fact,
            }
        )
        group["observed_excise_duty"] = str(Decimal(group["observed_excise_duty"]) + Decimal(fact["duty"]))


def add_frozen_adjustments(current, adjustments):
    """Carry the original duty/levy/GST into the open entry, never reprice it."""
    from datetime import date

    from app.features.compliant.modules.nz_alcohol.excise import entry_lines

    for adjustment in adjustments:
        fact = adjustment.get("frozen_basis")
        if not fact:
            continue
        removal = SimpleNamespace(
            frozen_basis=fact, occurred_on=date.fromisoformat(adjustment["date"]), reference=adjustment["reference"]
        )
        temporary = {
            "entry": entry_lines({}, [], date.fromisoformat(fact["rate_date"])),
            "lines": [],
            "problems": [],
            "total_lal": "0",
            "total_duty": "0",
        }
        add_frozen_lines(temporary, [removal])
        row = temporary["entry"]["lines"][0]
        row["line"] = len(current["entry"]["lines"]) + 1
        row["belongs_to"] = adjustment["belongs_to"]
        current["entry"]["lines"].append(row)
        for key in ("total_duty", "total_levy", "total_gst", "total"):
            current["entry"][key] = str(Decimal(current["entry"][key]) + Decimal(temporary["entry"][key]))
        current["total_duty"] = str(Decimal(current["total_duty"]) + Decimal(fact["duty"]))
        current["total_lal"] = str(Decimal(current["total_lal"]) + Decimal(fact["lal"]))
