from app.services import ascii_parser

def test_ascii_parser_stub():
    txt = "THTEST-123    0123456789 20250101\n"
    xml = ascii_parser.parse_ascii_to_xml(txt, "app/data/mappings/alberta_spin2_ascii_v1.yaml")
    assert "<TitleNumber>TEST-123" in xml
