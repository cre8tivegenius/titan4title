from lxml import etree

from app.services import pdf_ingest


def _line(text: str) -> pdf_ingest.TextLine:
    return pdf_ingest.TextLine(text=text, upper=text.upper(), page=0, bbox=(0.0, 0.0, 0.0, 0.0))


def test_pdf_ingest_returns_candidate_with_detected_fields(monkeypatch):
    lines = [
        _line("Certificate of Title"),
        _line("Order Number 1234567"),
        _line("Title Number 002345678901"),
        _line("LINC Number 0034567890"),
        _line("Legal Description"),
        _line("LOT 1 BLOCK 2 PLAN 2314KS"),
        _line("Registered Owner(s)"),
        _line("1. DOE JOHN A 1/2"),
        _line("Encumbrances, Liens & Interests"),
        _line("202312345678 2024/02/01 MORTGAGE Mortgage to Big Bank"),
    ]

    monkeypatch.setattr(pdf_ingest, "_extract_text_lines", lambda _: lines)

    candidates, confidence = pdf_ingest.pdf_to_xml_candidates(b"%PDF")
    assert candidates
    assert confidence > 0.5

    root = etree.fromstring(candidates[0].encode("utf-8"))
    assert root.findtext("TitleData/Title/TitleNumber") == "002345678901"
    instrument = root.find("TitleData/Title/Instruments/Instrument")
    assert instrument is not None
    assert instrument.findtext("DocumentType/PrintText") == "Mortgage to Big Bank"


def test_pdf_ingest_requires_core_identifiers(monkeypatch):
    # Missing title number should yield zero candidates.
    lines = [
        _line("Some Unrelated Text"),
        _line("LINC Number 0034567890"),
    ]
    monkeypatch.setattr(pdf_ingest, "_extract_text_lines", lambda _: lines)

    candidates, confidence = pdf_ingest.pdf_to_xml_candidates(b"%PDF")
    assert candidates == []
    assert confidence == 0.0
