"""Utilities for constructing canonical XML for new title requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Dict, Iterable, List, Optional, Sequence

from lxml import etree

from app.services.ascii_parser import build_document_tree
from app.utils import hashing


DEFAULT_TEMPLATE_ID = "alberta_title_v1"
DEFAULT_RIGHTS_TYPE = "Surface"
DEFAULT_ESTATE = "Fee Simple"
DEFAULT_TENANCY_TYPE = "Sole Owner"


@dataclass(slots=True)
class TitleBuildResult:
    xml: str
    title_number: str
    registration_number: str
    linc_number: str


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())


def _format_title_number(value: str) -> str:
    digits = re.sub(r"\s+", "", value)
    groups = [digits[i : i + 3] for i in range(0, len(digits), 3)]
    return " ".join(groups)


def _numeric_token(seed: str, length: int) -> str:
    if length <= 0:
        raise ValueError("length must be positive")
    digest = hashing.sha256_hex(seed.encode("utf-8"))
    max_value = 10 ** length
    min_value = 10 ** (length - 1)
    window = max_value - min_value
    value = int(digest[:16], 16) % window
    return str(min_value + value).zfill(length)


def _resolve_numeric(value: str | None, seed: str, length: int) -> str:
    digits = re.sub(r"\D", "", value or "")
    if digits:
        if len(digits) < length:
            digits = digits.zfill(length)
        else:
            digits = digits[:length]
        if set(digits) == {"0"}:
            return _numeric_token(seed, length)
        return digits
    return _numeric_token(seed, length)


def _split_legal_description(text: str) -> List[str]:
    lines = [line.strip() for line in text.replace("\r", "").split("\n") if line.strip()]
    if lines:
        return lines
    normalized = _normalize_whitespace(text)
    return [normalized] if normalized else []


def _format_currency(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}"


def _municipality_code(name: str) -> str:
    upper = re.sub(r"[^A-Z]", "", name.upper())
    return (upper[:4] or "MUNI").ljust(4, "X")


def _normalize_owner_groups(
    owner_groups: Optional[Sequence[Dict[str, object]]],
    default_name: str,
    default_tenancy: str,
) -> List[Dict[str, object]]:
    if owner_groups:
        normalized: List[Dict[str, object]] = []
        for raw_group in owner_groups:
            parties_data = raw_group.get("parties") or []
            parties = []
            for raw_party in parties_data:
                name = _normalize_whitespace(str(raw_party.get("name", ""))) if raw_party else ""
                if not name:
                    continue
                parties.append(
                    {
                        "name": name,
                        "type": raw_party.get("type", "Individual"),
                        "aliases": raw_party.get("aliases") or [],
                        "occupation": raw_party.get("occupation"),
                        "address_lines": raw_party.get("address_lines"),
                        "province": raw_party.get("province"),
                        "postal_code": raw_party.get("postal_code"),
                        "role": raw_party.get("role"),
                    }
                )
            if not parties:
                continue
            normalized.append(
                {
                    "tenancy_type": raw_group.get("tenancy_type") or default_tenancy,
                    "interest": raw_group.get("interest"),
                    "parties": parties,
                }
            )
        if normalized:
            return normalized

    return [
        {
            "tenancy_type": default_tenancy,
            "interest": "100%",
            "parties": [
                {
                    "name": _normalize_whitespace(default_name),
                    "type": "Individual",
                }
            ],
        }
    ]


def _collect_party_names(groups: Iterable[Dict[str, object]]) -> List[str]:
    names: List[str] = []
    for group in groups:
        for party in group.get("parties", []) or []:
            name = party.get("name")
            if name:
                names.append(str(name))
    return names


def build_new_title_xml(
    *,
    reference_number: str,
    buyer_name: str,
    purchase_price: Decimal,
    purchase_date: date,
    legal_description: str,
    municipality_name: str,
    municipality_code: str | None = None,
    title_number: str | None = None,
    registration_number: str | None = None,
    linc_number: str | None = None,
    rights_type: str = DEFAULT_RIGHTS_TYPE,
    estate: str = DEFAULT_ESTATE,
    tenancy_type: str = DEFAULT_TENANCY_TYPE,
    owner_groups: Optional[Sequence[Dict[str, object]]] = None,
) -> TitleBuildResult:
    if not reference_number.strip():
        raise ValueError("reference_number is required")
    if not buyer_name.strip():
        raise ValueError("buyer_name is required")
    if purchase_price <= 0:
        raise ValueError("purchase_price must be positive")
    if not legal_description.strip():
        raise ValueError("legal_description is required")
    if not municipality_name.strip():
        raise ValueError("municipality is required")

    title_seed = f"{reference_number}|{buyer_name}|{purchase_date.isoformat()}"
    resolved_title_number = _resolve_numeric(title_number, seed=title_seed, length=12)
    resolved_registration = _resolve_numeric(registration_number, seed=f"{title_seed}|REG", length=12)
    resolved_linc = _resolve_numeric(linc_number, seed=f"{title_seed}|LINC", length=10)

    short_legal = _normalize_whitespace(legal_description)[:120] or "UNSPECIFIED PARCEL"
    legal_lines = _split_legal_description(legal_description)

    municipality = {
        "code": municipality_code or _municipality_code(municipality_name),
        "name": municipality_name,
    }

    owners = _normalize_owner_groups(owner_groups, default_name=buyer_name, default_tenancy=tenancy_type)
    owner_names = _collect_party_names(owners)
    transfer_to = ", ".join(owner_names) if owner_names else buyer_name

    registration = {
        "document_number": resolved_registration,
        "date": purchase_date.isoformat(),
        "document_type_code": "TFRS",
        "document_type_name": "Transfer of Land",
        "document_type_print_text": f"Transfer to {transfer_to}",
        "value": _format_currency(purchase_price),
        "consideration_amount": _format_currency(purchase_price),
    }

    parcel = {
        "linc_number": resolved_linc,
        "short_legal_type": "ATS",
        "short_legal": short_legal,
        "legal_text": legal_lines or [short_legal],
    }

    instrument = {
        "registration_number": resolved_registration,
        "formatted_registration_number": resolved_registration,
        "registration_date": purchase_date.isoformat(),
        "document_type_code": "TFRS",
        "document_type_name": "Transfer of Land",
        "document_type_print_text": f"Consideration { _format_currency(purchase_price) } paid in full",
        "value": _format_currency(purchase_price),
    }

    document: Dict[str, Dict[str, object]] = {
        "order_number": reference_number,
        "title": {
            "title_number": resolved_title_number,
            "formatted_title_number": _format_title_number(resolved_title_number),
            "type": "Title",
            "rights_type": rights_type,
            "consolidated": False,
            "create_date": purchase_date.isoformat(),
            "short_legal_description": short_legal,
            "estate": estate,
            "municipality": municipality,
            "registration": registration,
            "parcels": [parcel],
            "owners": owners,
            "instruments": [instrument],
        },
    }

    xml_root = build_document_tree(document)
    xml_str = etree.tostring(xml_root, pretty_print=True, encoding="utf-8").decode("utf-8")
    return TitleBuildResult(
        xml=xml_str,
        title_number=resolved_title_number,
        registration_number=resolved_registration,
        linc_number=resolved_linc,
    )
