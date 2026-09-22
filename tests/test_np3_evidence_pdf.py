"""Focused checks for the self-contained NP3 evidence-register PDF."""

from io import BytesIO

from PIL import Image as PilImage
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from app.features.compliant.np3_evidence_pdf import build_np3_evidence_register_pdf


def _audit():
    return {
        "verification": {"date": "2026-09-19", "verifier": "Verifier", "location": "Site"},
        "rows": [
            {
                "category": "Documentation and record keeping",
                "control_id": "documentation-record-keeping",
                "topic": "Keep records",
                "requirement_summary": "Keep accurate records.",
                "state": "ready",
                "history": [
                    {
                        "title": "Daily review",
                        "created_at": "2026-09-19T08:30:00Z",
                        "signed_off_by": "Operations manager",
                        "how_we_meet": "The register is reviewed before production starts.",
                        "evidence_fields": {"review_result": "No gaps found"},
                    }
                ],
                "derived_evidence": [{"title": "Active Core evidence", "detail": "Evidence file retained in Core."}],
            },
            {
                "category": "Documentation and record keeping",
                "control_id": "delegation",
                "topic": "Delegation",
                "requirement_summary": "Record who is delegated.",
                "state": "ready",
                "history": [],
                "derived_evidence": [],
            },
            {
                "category": "Traceability",
                "control_id": "trace-and-recall",
                "topic": "Trace and recall",
                "requirement_summary": "Trace product to its inputs.",
                "state": "missing",
                "history": [],
                "derived_evidence": [],
            },
        ],
    }


def _png() -> bytes:
    image = PilImage.new("RGB", (80, 40), color="navy")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "Original uploaded PDF evidence")
    canvas.save()
    return output.getvalue()


def test_register_pdf_orders_checks_and_includes_recorded_answers_and_images():
    output = build_np3_evidence_register_pdf(
        _audit(),
        [{"file_name": "cleaning-photo.png", "mime_type": "image/png", "content": _png(), "checksum_sha256": "a" * 64}],
    )

    reader = PdfReader(BytesIO(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert output.startswith(b"%PDF-")
    assert text.index("Documentation and record keeping") < text.index("Traceability")
    assert "The register is reviewed before production starts." in text
    assert "cleaning-photo.png" in text


def test_register_pdf_flows_checks_in_one_section_together_but_breaks_page_between_sections():
    output = build_np3_evidence_register_pdf(_audit(), [])
    reader = PdfReader(BytesIO(output))

    # cover, "Documentation and record keeping" (2 checks, compact -- not one page each),
    # then a fresh page for "Traceability".
    assert len(reader.pages) == 3
    assert "Page 1" in (reader.pages[0].extract_text() or "")
    assert "Page 2" in (reader.pages[1].extract_text() or "")
    assert "Page 3" in (reader.pages[2].extract_text() or "")
    same_section_page = reader.pages[1].extract_text() or ""
    assert "Keep records" in same_section_page and "Delegation" in same_section_page
    assert "Trace and recall" in (reader.pages[2].extract_text() or "")
    assert "Trace and recall" not in same_section_page  # a new category starts its own page


def test_register_pdf_appends_uploaded_pdf_and_embeds_non_renderable_upload():
    output = build_np3_evidence_register_pdf(
        _audit(),
        [
            {
                "file_name": "supplier-certificate.pdf",
                "mime_type": "application/pdf",
                "content": _pdf(),
                "checksum_sha256": "b" * 64,
            },
            {
                "file_name": "instrument-export.bin",
                "mime_type": "application/octet-stream",
                "content": b"binary evidence",
                "checksum_sha256": "c" * 64,
            },
        ],
    )

    reader = PdfReader(BytesIO(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Original uploaded PDF evidence" in text
    assert "instrument-export.bin" in text
    assert len(reader.pages) >= 5


def test_staff_training_is_one_row_per_person_per_date_with_names_and_competency():
    def entry(person, day, topic):
        return {
            "employee_name": person,
            "fields": {"event_date": day, "employee_name": person, "training_topic": topic},
        }

    audit = _audit()
    audit["rows"][0].update(
        control_id="staff-competency",
        topic="Competency in management",
        log_entries=[
            entry("Nikolai Scott", "2026-02-02", "cleaning-and-sanitising"),
            entry("Johnny Dempsey", "2025-02-02", "hand-washing-clean-clothing"),
            entry("Johnny Dempsey", "2026-02-02", "cleaning-and-sanitising"),
            entry("Johnny Dempsey", "2026-02-02", "hand-washing-clean-clothing"),
        ],
    )

    text = "\n".join(
        page.extract_text() for page in PdfReader(BytesIO(build_np3_evidence_register_pdf(audit, []))).pages
    )

    assert text.count("Johnny Dempsey") == 2  # one row per date, not one per training
    assert "Hand washing and wearing clean clothing; Cleaning and sanitising" in text.replace("\n", " ")
    assert "hand-washing-clean-clothing" not in text  # readable names, not stored keys
    assert text.count("Competent") >= 3
    assert text.index("Johnny Dempsey") < text.index("Nikolai Scott")
