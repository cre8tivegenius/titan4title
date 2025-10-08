from app.services import renderer
import hashlib

XML = '<Title><TitleNumber>TEST-123</TitleNumber><Owners/><Instruments/></Title>'

def test_pdf_determinism():
    pdf1 = renderer.render(XML)
    pdf2 = renderer.render(XML)
    assert hashlib.sha256(pdf1).hexdigest() == hashlib.sha256(pdf2).hexdigest()
