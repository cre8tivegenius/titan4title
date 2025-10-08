"""Ingest legacy Alberta title PDFs to candidate canonical XML."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from .ascii_parser import build_document_tree

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextLine:
    text: str
    upper: str
    page: int
    bbox: Tuple[float, float, float, float]


DATE_PATTERNS: Sequence[str] = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y")
COMPANY_HINTS = (" INC", " LTD", " CORPORATION", " CORP", " COMPANY", " LIMITED", " LLP")
SECTION_HEADERS = (
    "LEGAL DESCRIPTION",
    "REGISTERED OWNER",
    "REGISTERED OWNER(S)",
    "ENCUMBRANCES",
    "INCUMBRANCES",
    "LIENS",
    "INSTRUMENTS",
    "TOTAL",
)


def _extract_text_lines(pdf_bytes: bytes) -> List[TextLine]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("PyMuPDF (fitz) is required for PDF ingest operations.") from exc

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    lines: List[TextLine] = []

    for page_index, page in enumerate(doc):
        words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
        if not words:
            continue
        grouped: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for x0, y0, x1, y1, word, block, line_no, word_no in words:
            key = (block, line_no)
            entry = grouped.setdefault(
                key,
                {
                    "words": [],
                    "bbox": [x0, y0, x1, y1],
                },
            )
            entry["words"].append((word_no, word, x0))
            entry["bbox"][0] = min(entry["bbox"][0], x0)
            entry["bbox"][1] = min(entry["bbox"][1], y0)
            entry["bbox"][2] = max(entry["bbox"][2], x1)
            entry["bbox"][3] = max(entry["bbox"][3], y1)

        for (block, line_no), entry in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
            sorted_words = sorted(entry["words"], key=lambda w: (w[0], w[2]))
            text = " ".join(word for _, word, _ in sorted_words).strip()
            if not text:
                continue
            bbox = tuple(entry["bbox"])  # type: ignore[arg-type]
            lines.append(TextLine(text=text, upper=text.upper(), page=page_index, bbox=bbox))

    return lines


def _normalize_date(value: str) -> Optional[str]:
    cleaned = value.strip()
    cleaned = cleaned.replace(".", "/").replace("-", "/")
    for pattern in DATE_PATTERNS:
        try:
            dt = datetime.strptime(cleaned, pattern.replace("-", "/"))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _format_title_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value)
    if not cleaned:
        return None
    groups = [cleaned[i : i + 3] for i in range(0, len(cleaned), 3)]
    return " ".join(groups)


def _detect_section(lines: Sequence[TextLine], header: str) -> Optional[int]:
    header_upper = header.upper()
    for idx, line in enumerate(lines):
        if header_upper in line.upper:
            return idx
    return None


def _is_section_break(text: str) -> bool:
    upper = text.upper()
    return any(header in upper for header in SECTION_HEADERS)


def _collect_until(lines: Sequence[TextLine], start_idx: int, stop_words: Iterable[str]) -> List[str]:
    stop_upper = [word.upper() for word in stop_words]
    collected: List[str] = []
    for line in lines[start_idx:]:
        if not line.text.strip():
            if collected:
                break
            continue
        upper = line.upper
        if any(stop in upper for stop in stop_upper):
            break
        collected.append(line.text.strip())
    return collected


def _extract_title_number(lines: Sequence[TextLine]) -> Optional[str]:
    for idx, line in enumerate(lines):
        match = re.search(r"TITLE\s+NUMBER\s*[:#-]?\s*([A-Z0-9-]+)", line.text, re.IGNORECASE)
        if match:
            return match.group(1)
        if "TITLE NUMBER" in line.upper and idx + 1 < len(lines):
            next_line = lines[idx + 1].text.strip()
            match = re.search(r"([A-Z0-9-]{6,})", next_line)
            if match:
                return match.group(1)
    return None


def _extract_order_number(lines: Sequence[TextLine]) -> Optional[str]:
    for line in lines[:10]:  # typically near the top of page 1
        match = re.search(r"ORDER\s+NUMBER\s*[:#-]?\s*(\d+)", line.text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_linc(lines: Sequence[TextLine]) -> Optional[str]:
    for idx, line in enumerate(lines):
        if "LINC" not in line.upper:
            continue
        match = re.search(r"(\d{10})", line.text)
        if match:
            return match.group(1)
        if idx + 1 < len(lines):
            match = re.search(r"(\d{10})", lines[idx + 1].text)
            if match:
                return match.group(1)
    return None


def _extract_municipality(lines: Sequence[TextLine]) -> Optional[str]:
    for line in lines:
        match = re.search(r"MUNICIPALITY\s*[:#-]?\s*(.+)$", line.text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_legal_description(lines: Sequence[TextLine]) -> List[str]:
    idx = _detect_section(lines, "LEGAL DESCRIPTION")
    if idx is None:
        return []
    return [line for line in _collect_until(lines, idx + 1, ("REGISTERED OWNER", "ENCUMBRANCES")) if line]


def _classify_owner_type(name: str) -> str:
    upper = name.upper()
    return "Company" if any(hint in upper for hint in COMPANY_HINTS) else "Individual"


def _extract_owners(lines: Sequence[TextLine]) -> List[Dict[str, Any]]:
    idx = _detect_section(lines, "REGISTERED OWNER")
    if idx is None:
        return []
    collected = _collect_until(lines, idx + 1, ("ENCUMBRANCES", "INSTRUMENTS"))
    owners: List[Dict[str, Any]] = []
    for line in collected:
        raw = line.strip()
        if not raw:
            continue
        raw = re.sub(r"^\d+\.?\s*", "", raw)
        interest = None
        interest_match = re.search(r"(\d+/\d+)", raw)
        if interest_match:
            interest = interest_match.group(1)
            raw = raw.replace(interest, "").strip()
        tenancy = "Joint Tenants" if "JOINT" in raw.upper() else "Common"
        cleaned_name = raw.replace("JOINT TENANTS", "").replace("JOINT", "").strip(",; ")
        owners.append(
            {
                "name": cleaned_name or raw,
                "tenancy": tenancy,
                "interest": interest,
                "type": _classify_owner_type(cleaned_name or raw),
            }
        )
    return owners


def _parse_instrument_line(text: str) -> Optional[Dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if len(parts) < 2 or not re.fullmatch(r"\d{6,}", parts[0]):
        return None
    registration_number = parts[0]
    idx = 1
    registration_date = None
    if idx < len(parts):
        maybe_date = _normalize_date(parts[idx])
        if maybe_date:
            registration_date = maybe_date
            idx += 1
    # Collect uppercase tokens for type until remarks
    type_tokens: List[str] = []
    while idx < len(parts):
        token = parts[idx]
        if re.fullmatch(r"\d{6,}", token):
            break
        if len(token) == 1:
            break
        # Stop when remarks likely start (mixed case)
        if not token.isupper():
            break
        type_tokens.append(token)
        idx += 1
    doc_type = " ".join(type_tokens).strip() or "Instrument"
    remarks = " ".join(parts[idx:]).strip()
    doc_code = re.sub(r"[^A-Z]", "", doc_type)[:4] or doc_type[:4].upper()
    return {
        "registration_number": registration_number,
        "registration_date": registration_date,
        "document_type_name": doc_type.title(),
        "document_type_code": doc_code,
        "remarks": remarks,
    }


def _extract_instruments(lines: Sequence[TextLine]) -> List[Dict[str, Any]]:
    idx = _detect_section(lines, "ENCUMBRANCES")
    if idx is None:
        idx = _detect_section(lines, "INSTRUMENTS")
    if idx is None:
        return []
    collected = _collect_until(lines, idx + 1, ("TOTAL",))
    instruments: List[Dict[str, Any]] = []
    for line in collected:
        parsed = _parse_instrument_line(line)
        if parsed:
            instruments.append(parsed)
    return instruments


def _build_document(extracted: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title_number = extracted.get("title_number")
    instruments: List[Dict[str, Any]] = extracted.get("instruments", [])
    if not title_number:
        return None

    first_instrument = instruments[0] if instruments else None
    registration_number = extracted.get("registration_document_number") or (
        first_instrument["registration_number"] if first_instrument else title_number
    )
    registration_date = extracted.get("issue_date") or (
        first_instrument.get("registration_date") if first_instrument else None
    )
    if not registration_date:
        return None
    document_type_name = extracted.get("registration_document_type") or (
        first_instrument.get("document_type_name") if first_instrument else "Title"
    )
    document_type_code = extracted.get("registration_document_code") or (
        first_instrument.get("document_type_code") if first_instrument else "TITL"
    )

    owner_groups: List[Dict[str, Any]] = []
    for idx, owner in enumerate(extracted.get("owners", [])):
        owner_groups.append(
            {
                "tenancy_type": owner.get("tenancy"),
                "interest": owner.get("interest"),
                "parties": [
                    {
                        "sequence": idx + 1,
                        "name": owner.get("name"),
                        "type": owner.get("type", "Individual"),
                        "occupation": None,
                        "role": None,
                        "aliases": [],
                        "address_lines": [],
                        "province": None,
                        "postal_code": None,
                    }
                ],
            }
        )

    linc_number = extracted.get("linc_number")
    if not linc_number:
        return None

    document: Dict[str, Any] = {
        "order_number": extracted.get("order_number") or registration_number,
        "title": {
            "title_number": title_number,
            "formatted_title_number": _format_title_number(title_number),
            "type": "Title",
            "rights_type": extracted.get("rights_type") or "Surface",
            "consolidated": False,
            "create_date": registration_date,
            "expiry_date": None,
            "short_legal_description": (extracted.get("legal_description") or [None])[0],
            "estate": extracted.get("estate"),
            "municipality": {"code": None, "name": extracted.get("municipality")},
            "registration": {
                "document_number": registration_number,
                "date": registration_date,
                "document_type_code": document_type_code,
                "document_type_name": document_type_name,
                "document_type_print_text": extracted.get("registration_print_text"),
                "value": None,
                "consideration_amount": None,
                "consideration_text": None,
            },
            "parcels": [
                {
                    "sequence": 1,
                    "linc_number": linc_number,
                    "short_legal_type": "ATS",
                    "short_legal": (extracted.get("legal_description") or [None])[0],
                    "legal_text": extracted.get("legal_description") or [],
                    "rights_text": [],
                }
            ],
            "owners": owner_groups,
            "instruments": [
                {
                    "sequence": idx + 1,
                    "registration_number": inst["registration_number"],
                    "formatted_registration_number": inst["registration_number"],
                    "registration_date": inst.get("registration_date"),
                    "document_type_code": inst.get("document_type_code"),
                    "document_type_name": inst.get("document_type_name"),
                    "document_type_print_text": inst.get("remarks"),
                    "discharge_date": None,
                    "value": None,
                    "remarks": [inst.get("remarks")],
                }
                for idx, inst in enumerate(instruments)
            ],
        },
    }
    return document


def _extract_metadata(lines: Sequence[TextLine]) -> Dict[str, Any]:
    extracted: Dict[str, Any] = {}
    extracted["order_number"] = _extract_order_number(lines)
    extracted["title_number"] = _extract_title_number(lines)
    extracted["linc_number"] = _extract_linc(lines)
    extracted["municipality"] = _extract_municipality(lines)
    legal_description = _extract_legal_description(lines)
    if legal_description:
        extracted["legal_description"] = legal_description
    owners = _extract_owners(lines)
    if owners:
        extracted["owners"] = owners
    instruments = _extract_instruments(lines)
    if instruments:
        extracted["instruments"] = instruments
    return extracted


def pdf_to_xml_candidates(pdf_bytes: bytes) -> Tuple[List[str], float]:
    """Produce 1-3 canonical XML candidates from a prior title PDF."""

    try:
        lines = _extract_text_lines(pdf_bytes)
    except RuntimeError as exc:  # pragma: no cover - dependency guard
        LOGGER.error("PDF ingestion failed: %s", exc)
        return [], 0.0

    if not lines:
        return [], 0.0

    extracted = _extract_metadata(lines)
    document = _build_document(extracted)
    if not document:
        return [], 0.0

    try:
        xml_root = build_document_tree(document)
    except ValueError as exc:
        LOGGER.warning("Unable to build canonical XML from PDF: %s", exc)
        return [], 0.0

    xml_str = etree.tostring(xml_root, pretty_print=True, encoding="utf-8").decode("utf-8")

    confidence = 0.2
    if extracted.get("title_number"):
        confidence += 0.3
    if extracted.get("owners"):
        confidence += 0.2
    if extracted.get("instruments"):
        confidence += 0.2
    if extracted.get("legal_description"):
        confidence += 0.1
    confidence = min(confidence, 0.95)

    return [xml_str], confidence
