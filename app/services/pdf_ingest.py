from typing import List, Tuple
import fitz  # PyMuPDF
import re
from lxml import etree

def pdf_to_xml_candidates(pdf_bytes: bytes) -> Tuple[List[str], float]:
    """Heuristic PDF ingest (text-based PDFs): looks for key labels and emits a minimal XML.

    Replace with positioned extraction if required.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "\n".join(page.get_text("text") for page in doc)
    # title number
    tn = None
    for pat in [r"Title\s*Number\s*[:#]\s*(\S+)", r"Certificate\s+of\s+Title\s+No\.?\s*(\S+)"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            tn = m.group(1).strip()
            break
    root = etree.Element("Title")
    etree.SubElement(root, "TitleNumber").text = tn or ""
    etree.SubElement(root, "Owners")
    etree.SubElement(root, "Instruments")
    xml = etree.tostring(root, pretty_print=True, encoding="utf-8").decode("utf-8")
    confidence = 0.7 if tn else 0.3
    return [xml], confidence
