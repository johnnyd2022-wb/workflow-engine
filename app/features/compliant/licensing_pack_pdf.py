"""The licensing inspector pack (plan 2.5): one PDF with licences, managers, checks,
staff training and the incident and refusal log."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_INK = colors.HexColor("#123f3a")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("LicTitle", parent=base["Title"], fontSize=20, leading=25, textColor=_INK),
        "sub": ParagraphStyle(
            "LicSub", parent=base["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#52606d")
        ),
        "h": ParagraphStyle("LicH", parent=base["Heading2"], fontSize=13, leading=17, textColor=_INK, spaceBefore=10),
        "cell": ParagraphStyle("LicCell", parent=base["Normal"], fontSize=8, leading=10),
        "head": ParagraphStyle("LicHead", parent=base["Normal"], fontSize=8, leading=10, fontName="Helvetica-Bold"),
    }


def _p(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape("" if value is None else str(value)).replace("\n", "<br/>"), style)


def _table(story: list, headers: list[str], rows: list[list[Any]], widths: list[float], st: dict, empty: str) -> None:
    if not rows:
        story.append(_p(empty, st["sub"]))
        return
    data = [[_p(h, st["head"]) for h in headers]] + [[_p(c, st["cell"]) for c in row] for row in rows]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f3f1")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d3d8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)


def build_licensing_pack_pdf(org_name: str, data: dict, training: list[dict], generated_by: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm
    )
    st = _styles()
    story: list = [
        _p(f"{org_name}: alcohol licensing records", st["title"]),
        _p(
            f"Generated {datetime.now(UTC).strftime('%-d %b %Y %H:%M UTC')} by {generated_by}. Records as kept in "
            "the licensing register; the licence and its conditions are the authority.",
            st["sub"],
        ),
        Spacer(1, 4 * mm),
        _p("Licences", st["h"]),
    ]
    _table(
        story,
        ["Licence", "Number", "DLC", "Premises / event", "Issued", "Expires", "Renew by", "Hours", "Status"],
        [
            [
                lic["kind_label"] + ("\n" + ", ".join(lic["endorsement_labels"]) if lic["endorsement_labels"] else ""),
                lic["licence_number"],
                lic["issuing_dlc"],
                (
                    lic["event_name"]
                    + f" ({lic['event_starts_on']} to {lic['event_ends_on']})\nManager: "
                    + (lic["manager_on_duty"] or "not named")
                )
                if lic["kind"] == "special"
                else lic["premises"],
                lic["issued_on"],
                lic["expires_on"],
                lic["renewal_file_by"],
                "\n".join(
                    x
                    for x in (
                        f"Sale: {lic['sale_hours']}" if lic["sale_hours"] else "",
                        f"Delivery: {lic['delivery_hours_start']}-{lic['delivery_hours_end']}"
                        if lic["delivery_hours_start"]
                        else "",
                    )
                    if x
                ),
                lic["state_label"],
            ]
            for lic in data["licences"]
        ],
        [30, 32, 26, 50, 20, 20, 20, 34, 38],
        st,
        "No licences recorded.",
    )
    story.append(_p("Managers' certificates", st["h"]))
    _table(
        story,
        ["Holder", "Certificate", "DLC", "Issued", "Expires", "Status"],
        [
            [
                m["holder_name"],
                m["certificate_number"],
                m["issuing_dlc"],
                m["issued_on"],
                m["expires_on"],
                m["state_label"],
            ]
            for m in data["managers"]
        ],
        [50, 40, 45, 25, 25, 85],
        st,
        "No managers' certificates recorded.",
    )
    story.append(_p("Policies, displays and checks", st["h"]))
    _table(
        story,
        ["Check", "Latest record", "Evidence", "Recorded", "Review due", "Status"],
        [
            [
                c["description"],
                c["latest"]["title"] if c["latest"] else ("From the register" if c["from_register"] else "None"),
                c["latest"]["evidence_reference"] if c["latest"] else "",
                c["latest"]["recorded_on"] if c["latest"] else "",
                c["latest"]["review_due"] if c["latest"] else "",
                c["reason"],
            ]
            for c in data["checks"]
        ],
        [80, 50, 50, 22, 22, 46],
        st,
        "No checks.",
    )
    story.append(_p("Staff training", st["h"]))
    _table(
        story,
        ["Training", "Recorded", "Refresh by", "Evidence"],
        [[t["title"], t["recorded_on"], t["due_date"], t["evidence_reference"]] for t in training],
        [120, 30, 30, 90],
        st,
        "No training recorded.",
    )
    story.append(_p("Incident and refusal log", st["h"]))
    _table(
        story,
        ["When", "Type", "Where", "What happened", "Action taken", "Staff", "Reference"],
        [
            [
                e["occurred_at"][:16].replace("T", " "),
                e["kind_label"],
                e["location"],
                e["description"],
                e["action_taken"],
                e["staff_name"],
                e["reference"],
            ]
            for e in data["log"]
        ],
        [28, 40, 28, 70, 60, 26, 20],
        st,
        "No entries. The log is kept even when there's nothing to record.",
    )
    doc.build(story)
    return buf.getvalue()
