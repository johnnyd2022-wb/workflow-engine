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
                "derived_evidence": [
                    {"title": "Active Core evidence", "detail": "Evidence file retained in Core."}
                ],
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


def test_register_pdf_flows_multiple_checks_together_and_numbers_pages_globally():
    output = build_np3_evidence_register_pdf(_audit(), [])
    reader = PdfReader(BytesIO(output))

    assert len(reader.pages) == 2  # cover + compact evidence pages, not one page/check
    assert "Page 1" in (reader.pages[0].extract_text() or "")
    assert "Page 2" in (reader.pages[1].extract_text() or "")
    assert "Keep records" in (reader.pages[1].extract_text() or "")
    assert "Trace and recall" in (reader.pages[1].extract_text() or "")


def test_register_pdf_appends_uploaded_pdf_and_embeds_non_renderable_upload():
    output = build_np3_evidence_register_pdf(
        _audit(),
        [
            {"file_name": "supplier-certificate.pdf", "mime_type": "application/pdf", "content": _pdf(), "checksum_sha256": "b" * 64},
            {"file_name": "instrument-export.bin", "mime_type": "application/octet-stream", "content": b"binary evidence", "checksum_sha256": "c" * 64},
        ],
    )

    reader = PdfReader(BytesIO(output))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "Original uploaded PDF evidence" in text
    assert "instrument-export.bin" in text
    assert len(reader.pages) >= 5
