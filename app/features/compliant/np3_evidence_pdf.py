"""Build the human-readable NP3 evidence register PDF.

The register is deliberately assembled on the server.  That keeps uploaded evidence in
the exported record (rather than leaving an auditor with a list of links that need an
active session), and preserves the same category/check order as the NP3 workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from io import BytesIO
from typing import Any

from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

_PAGE_WIDTH, _PAGE_HEIGHT = A4
_DOCUMENTATION_CONTROL = "documentation-record-keeping"


def _styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "NP3RegisterTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=31,
            textColor=colors.HexColor("#123f3a"),
        ),
        "subtitle": ParagraphStyle(
            "NP3RegisterSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#52606d"),
            alignment=TA_CENTER,
        ),
        "section": ParagraphStyle(
            "NP3RegisterSection",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=22,
            textColor=colors.HexColor("#123f3a"),
            spaceBefore=6,
            spaceAfter=10,
        ),
        "check": ParagraphStyle(
            "NP3RegisterCheck",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=colors.HexColor("#172033"),
            spaceBefore=5,
            spaceAfter=6,
        ),
        "label": ParagraphStyle(
            "NP3RegisterLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#175c52"),
            spaceBefore=6,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "NP3RegisterBody",
            parent=styles["Normal"],
            fontSize=9.4,
            leading=14,
            textColor=colors.HexColor("#27364a"),
            spaceAfter=4,
        ),
        "muted": ParagraphStyle(
            "NP3RegisterMuted",
            parent=styles["Normal"],
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#5d6778"),
            spaceAfter=4,
        ),
    }


def _text(value: Any) -> str:
    return escape("" if value is None else str(value)).replace("\n", "<br/>")


def _paragraph(story: list[Any], text: Any, style: ParagraphStyle) -> None:
    if text not in (None, "", {}, []):
        story.append(Paragraph(_text(text), style))


def _header_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#dce4e9"))
    canvas.line(18 * mm, 13 * mm, _PAGE_WIDTH - 18 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#5d6778"))
    canvas.drawString(18 * mm, 8.5 * mm, "NP3 evidence register")
    canvas.drawRightString(_PAGE_WIDTH - 18 * mm, 8.5 * mm, f"Page {document.page}")
    canvas.restoreState()


def _segment_with_footer(story: list[Any]) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="NP3 evidence register",
        author="Workflow Engine",
    )
    document.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()


def _append_document(writer: PdfWriter, story: list[Any]) -> None:
    writer.append(BytesIO(_segment_with_footer(story)))


def _answers(story: list[Any], row: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    history = row.get("history") or []
    story.append(Paragraph("Recorded answers", styles["label"]))
    if not history:
        story.append(Paragraph("No user response has been recorded for this check yet.", styles["muted"]))
        return
    for event in history:
        title = event.get("title") or "Recorded response"
        when = event.get("created_at") or "Date not recorded"
        signed = event.get("signed_off_by") or ""
        _paragraph(story, f"{title} · {when}" + (f" · {signed}" if signed else ""), styles["body"])
        _paragraph(story, event.get("how_we_meet"), styles["body"])
        for key, value in (event.get("evidence_fields") or {}).items():
            label = str(key).replace("_", " ").capitalize()
            _paragraph(story, f"{label}: {value}", styles["body"])


def _core_evidence(story: list[Any], row: dict[str, Any], styles: dict[str, ParagraphStyle]) -> None:
    evidence = row.get("derived_evidence") or []
    if not evidence:
        return
    story.append(Paragraph("Linked operational evidence", styles["label"]))
    for item in evidence:
        _paragraph(story, f"{item.get('title') or 'Operational evidence'} — {item.get('detail') or ''}", styles["body"])


def _image_story(evidence: dict[str, Any], styles: dict[str, ParagraphStyle]) -> tuple[list[Any], bool]:
    story: list[Any] = [Paragraph("Uploaded evidence", styles["label"])]
    _paragraph(story, f"{evidence['file_name']} · {evidence['mime_type']}", styles["body"])
    try:
        image = Image(BytesIO(evidence["content"]))
        image._restrictSize(170 * mm, 190 * mm)
        story.extend([Spacer(1, 3 * mm), image])
        return story, True
    except Exception:
        story.append(
            Paragraph(
                "This image could not be rendered, but its original file is embedded with this PDF.", styles["muted"]
            )
        )
    return story, False


def _attachment_cover(evidence: dict[str, Any], styles: dict[str, ParagraphStyle], note: str) -> list[Any]:
    return [
        Paragraph("Uploaded evidence", styles["section"]),
        Paragraph(_text(evidence["file_name"]), styles["check"]),
        Paragraph(_text(note), styles["body"]),
        Paragraph(
            _text(f"File type: {evidence['mime_type']} · SHA-256: {evidence.get('checksum_sha256') or 'not recorded'}"),
            styles["muted"],
        ),
    ]


def build_np3_evidence_register_pdf(audit: dict[str, Any], uploaded_evidence: list[dict[str, Any]]) -> bytes:
    """Return a printable, self-contained NP3 evidence register.

    Images are rendered inside the documentation/record-keeping check.  Uploaded PDFs
    are appended at that same point as their original pages.  A non-renderable upload is
    retained as a PDF attachment and given a readable cover page with its checksum.
    """
    styles = _styles()
    writer = PdfWriter()
    verification = audit.get("verification") or {}
    cover = [
        Spacer(1, 45 * mm),
        Paragraph("NP3 evidence register", styles["title"]),
        Spacer(1, 6 * mm),
        Paragraph("Verification evidence, answers and supporting files", styles["subtitle"]),
        Spacer(1, 18 * mm),
        Paragraph(_text(f"Prepared {datetime.now(UTC).strftime('%d %B %Y, %H:%M UTC')}"), styles["subtitle"]),
        Paragraph(_text(f"Verification date: {verification.get('date') or 'Not set'}"), styles["subtitle"]),
        Paragraph(_text(f"Verifier: {verification.get('verifier') or 'Not recorded'}"), styles["subtitle"]),
        Paragraph(_text(f"Location: {verification.get('location') or 'Not recorded'}"), styles["subtitle"]),
    ]
    _append_document(writer, cover)

    category = None
    for row in audit.get("rows") or []:
        story: list[Any] = []
        if row.get("category") != category:
            category = row.get("category")
            story.extend([Paragraph(_text(category), styles["section"]), Spacer(1, 2 * mm)])
        story.append(Paragraph(_text(row.get("topic")), styles["check"]))
        _paragraph(story, row.get("requirement_summary"), styles["body"])
        _paragraph(story, f"Current status: {str(row.get('state') or '').title()}", styles["muted"])
        _answers(story, row, styles)
        _core_evidence(story, row, styles)
        if row.get("control_id") == _DOCUMENTATION_CONTROL:
            for evidence in uploaded_evidence:
                mime_type = (evidence.get("mime_type") or "").lower()
                content = evidence.get("content")
                if not content:
                    story.extend(
                        _attachment_cover(
                            evidence,
                            styles,
                            "The original uploaded file was unavailable when this register was generated.",
                        )
                    )
                    continue
                if mime_type in {"image/jpeg", "image/jpg", "image/png"}:
                    image_story, rendered = _image_story(evidence, styles)
                    story.extend(image_story)
                    if not rendered:
                        writer.add_attachment(evidence["file_name"], content)
                    continue
                _append_document(writer, story)
                story = []
                _append_document(
                    writer, _attachment_cover(evidence, styles, "The original PDF pages follow this cover sheet.")
                )
                if mime_type == "application/pdf":
                    try:
                        writer.append(BytesIO(content))
                        continue
                    except Exception:
                        _append_document(
                            writer,
                            _attachment_cover(
                                evidence, styles, "The PDF could not be rendered. Its original file is embedded below."
                            ),
                        )
                writer.add_attachment(evidence["file_name"], content)
        if story:
            _append_document(writer, story)

    output = BytesIO()
    writer.write(output)
    return output.getvalue()
