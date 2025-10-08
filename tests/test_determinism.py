import hashlib

import pytest

pytest.importorskip("reportlab")

from app.services import renderer

XML = '<Title><TitleNumber>TEST-123</TitleNumber><Owners/><Instruments/></Title>'


def test_pdf_determinism():
    pdf1 = renderer.render(XML, options={"pdfa": False})
    pdf2 = renderer.render(XML, options={"pdfa": False})
    assert hashlib.sha256(pdf1).hexdigest() == hashlib.sha256(pdf2).hexdigest()


def test_renderer_sets_static_metadata():
    pdf_bytes = renderer.render(XML, options={"pdfa": False})
    assert b"D:20240101000000Z" in pdf_bytes
    assert b"Title Document Creator Pro" in pdf_bytes
