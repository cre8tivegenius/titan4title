"""Utilities for applying PDF/A-2b conformance using ReportLab."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

from reportlab.pdfbase import pdfdoc


LOGGER = logging.getLogger(__name__)


def _build_xmp(metadata: Dict[str, str]) -> str:
    template = f"""<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' xmlns:pdfaid='http://www.aiim.org/pdfa/ns/id/'>
  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
    <rdf:Description rdf:about='' xmlns:dc='http://purl.org/dc/elements/1.1/'>
      <dc:title>
        <rdf:Alt>
          <rdf:li xml:lang='x-default'>{metadata.get('title', 'Certificate of Title')}</rdf:li>
        </rdf:Alt>
      </dc:title>
      <dc:creator>
        <rdf:Seq>
          <rdf:li>{metadata.get('author', 'Land Titles Office')}</rdf:li>
        </rdf:Seq>
      </dc:creator>
    </rdf:Description>
    <rdf:Description rdf:about='' xmlns:pdfaid='http://www.aiim.org/pdfa/ns/id/'>
      <pdfaid:part>2</pdfaid:part>
      <pdfaid:conformance>B</pdfaid:conformance>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""
    return template


def apply_pdfa(canvas_obj, icc_path: str, metadata: Dict[str, str]) -> None:
    """Mutate the ReportLab canvas to comply with PDF/A-2b when an ICC profile is available."""

    profile_path = Path(icc_path)
    if not profile_path.exists():
        LOGGER.warning("ICC profile not found for PDF/A: %s", profile_path)
        return

    try:
        profile_bytes = profile_path.read_bytes()
    except Exception as exc:  # pragma: no cover - filesystem error guard
        LOGGER.warning("Unable to read ICC profile %s: %s", profile_path, exc)
        return

    pdf_stream = pdfdoc.PDFStream()
    pdf_stream.content = profile_bytes
    pdf_stream.dictionary[pdfdoc.PDFName("N")] = 3
    icc_ref = canvas_obj._doc.Reference(pdf_stream, internalName="ICCProfile")

    output_intent = pdfdoc.PDFDictionary(
        {
            pdfdoc.PDFName("Type"): pdfdoc.PDFName("OutputIntent"),
            pdfdoc.PDFName("S"): pdfdoc.PDFName("GTS_PDFA1"),
            pdfdoc.PDFName("DestOutputProfile"): icc_ref,
            pdfdoc.PDFName("OutputConditionIdentifier"): pdfdoc.PDFString("sRGB IEC61966-2.1"),
            pdfdoc.PDFName("Info"): pdfdoc.PDFString("sRGB IEC61966-2.1"),
        }
    )

    catalog = canvas_obj._doc.Catalog
    catalog[pdfdoc.PDFName("OutputIntents")] = pdfdoc.PDFArray([output_intent])

    canvas_obj._doc.xmpMetadata = _build_xmp(metadata)

