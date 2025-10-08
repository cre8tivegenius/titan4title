"""SPIN 2 ASCII → canonical XML converter.

This module reads fixed-width SPIN 2 exports according to a YAML mapping and
produces canonical XML that conforms to the published XSD. The mapping drives
field slicing and transformation rules; Python manages higher-level assembly of
the hierarchical XML structure (titles, parcels, owners, instruments, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml
from lxml import etree


__all__ = ["parse_ascii_to_xml", "build_document_tree", "Spin2AsciiParser"]


class MappingLoadError(RuntimeError):
    """Raised when the YAML mapping cannot be loaded or parsed."""


class RecordMatchError(RuntimeError):
    """Raised when a line matches a record but required fields are missing."""


def _format_title_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\s+", "", str(value))
    if not digits:
        return None
    groups = [digits[i : i + 3] for i in range(0, len(digits), 3)]
    return " ".join(groups)


def _format_registration_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _bool_text(value: bool) -> str:
    return "true" if bool(value) else "false"


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _date_transform(value: str, fmt: str, output: str = "%Y-%m-%d") -> str:
    dt = datetime.strptime(value, fmt)
    return dt.strftime(output)


def _apply_transform(value: Any, transform: Any) -> Any:
    if value is None:
        return None

    if isinstance(transform, str):
        if transform == "trim":
            return value.strip()
        if transform == "rstrip":
            return value.rstrip()
        if transform == "lstrip":
            return value.lstrip()
        if transform == "uppercase":
            return value.upper()
        if transform == "lowercase":
            return value.lower()
        if transform == "titlecase":
            return value.title()
        if transform == "normalize_spaces":
            return _normalize_spaces(value)
        if transform == "digits":
            return re.sub(r"\D", "", value)
        if transform == "int":
            value = value.strip()
            return int(value) if value else None
        raise ValueError(f"Unknown transform '{transform}'")

    if isinstance(transform, dict):
        if "map" in transform:
            mapping: Dict[str, Any] = transform["map"] or {}
            default = transform.get("default")
            return mapping.get(value, default if default is not None else value)
        if "date" in transform:
            fmt = transform["date"]
            output = transform.get("output", "%Y-%m-%d")
            return _date_transform(value, fmt, output)
        if "format" in transform:
            fmt_name = transform["format"]
            if fmt_name == "title_number_groups":
                return _format_title_number(value)
            if fmt_name == "registration_number":
                return _format_registration_number(value)
            raise ValueError(f"Unsupported format transform '{fmt_name}'")
        if "when" in transform:
            # Conditional: {when: value, then: result, else: fallback}
            expected = transform.get("when")
            then = transform.get("then")
            otherwise = transform.get("else", value)
            return then if value == expected else otherwise
        raise ValueError(f"Unsupported transform spec: {json.dumps(transform)}")

    return value


def _parse_field(line: str, field_spec: Dict[str, Any]) -> Any:
    if "value" in field_spec:
        value = field_spec["value"]
    else:
        start = field_spec.get("start") or field_spec.get("pos")
        length = field_spec.get("len") or field_spec.get("length")
        if start is None or length is None:
            raise ValueError("Field specification requires 'start' and 'len'.")
        start_idx = max(0, int(start) - 1)
        end_idx = start_idx + int(length)
        raw = line[start_idx:end_idx]
        value = raw

    transforms: List[Any] = list(field_spec.get("transforms") or [])
    if field_spec.get("trim", True) and "trim" not in transforms:
        transforms.insert(0, "trim")

    for transform in transforms:
        value = _apply_transform(value, transform)

    if value in ("", None):
        if "default" in field_spec:
            return field_spec["default"]
        return None

    return value


def _match_record(line: str, match_spec: Dict[str, Any]) -> bool:
    if not match_spec:
        return False
    if "equals" in match_spec:
        type_at = int(match_spec.get("type_at", 1)) - 1
        expected = match_spec["equals"]
        actual = line[type_at : type_at + len(expected)]
        if actual != expected:
            return False
    if "regex" in match_spec:
        if not re.match(match_spec["regex"], line):
            return False
    return True


@dataclass
class RecordSpec:
    record_id: str
    match: Dict[str, Any]
    fields: Dict[str, Dict[str, Any]]

    def try_parse(self, line: str) -> Optional[Dict[str, Any]]:
        if not _match_record(line, self.match):
            return None
        parsed: Dict[str, Any] = {}
        for name, field_spec in self.fields.items():
            parsed[name] = _parse_field(line, field_spec)
        return parsed


class Mapping:
    def __init__(self, raw: Dict[str, Any]):
        if "records" not in raw:
            raise MappingLoadError("Mapping file must define 'records'.")
        self.version: str = raw.get("version", "unknown")
        self.defaults: Dict[str, Any] = raw.get("defaults", {})
        self.records: List[RecordSpec] = [
            RecordSpec(record_id=entry["id"], match=entry.get("match", {}), fields=entry.get("fields", {}))
            for entry in raw["records"]
        ]


def _load_mapping(path: str | Path) -> Mapping:
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return Mapping(raw or {})


class Spin2AsciiParser:
    def __init__(self, mapping: Mapping):
        self.mapping = mapping
        self.order_number: Optional[str] = None
        self.title: Dict[str, Any] = {
            "title_number": None,
            "formatted_title_number": None,
            "type": mapping.defaults.get("title_type", "Title"),
            "rights_type": mapping.defaults.get("rights_type"),
            "consolidated": bool(mapping.defaults.get("consolidated", False)),
            "create_date": None,
            "expiry_date": None,
            "short_legal_description": None,
            "estate": None,
            "municipality": {"code": None, "name": None},
            "registration": {
                "document_number": None,
                "date": None,
                "document_type_code": None,
                "document_type_name": None,
                "document_type_print_text": None,
                "value": None,
                "consideration_amount": None,
                "consideration_text": None,
            },
            "parcels": [],
            "municipal_address": [],
            "owners": [],
            "instruments": [],
        }
        self._owner_groups: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
        self._owner_order: List[Tuple[str, Optional[str]]] = []
        self._current_owner_party: Optional[Dict[str, Any]] = None
        self._current_parcel: Optional[Dict[str, Any]] = None
        self._current_instrument: Optional[Dict[str, Any]] = None
        self._instrument_sequence: int = 0

    # ------------------------------------------------------------------
    # Record consumers
    def _handle_title_header(self, values: Dict[str, Any]) -> None:
        title = self.title
        title_number = values.get("title_number")
        if title_number:
            title["title_number"] = title_number
            if not values.get("formatted_title_number"):
                values["formatted_title_number"] = _format_title_number(title_number)
        if values.get("formatted_title_number"):
            title["formatted_title_number"] = values["formatted_title_number"]
        if values.get("rights_type"):
            title["rights_type"] = values["rights_type"]
        if values.get("consolidated_flag") is not None:
            title["consolidated"] = bool(values["consolidated_flag"])
        if values.get("create_date"):
            title["create_date"] = values["create_date"]
        if values.get("expiry_date"):
            title["expiry_date"] = values["expiry_date"]
        if values.get("short_legal_description"):
            title["short_legal_description"] = values["short_legal_description"]
        if values.get("estate"):
            title["estate"] = values["estate"]
        municipality = title["municipality"]
        if values.get("municipality_code"):
            municipality["code"] = values["municipality_code"]
        if values.get("municipality_name"):
            municipality["name"] = values["municipality_name"]
        if values.get("municipal_address"):
            title["municipal_address"].append(values["municipal_address"])
        registration = title["registration"]
        if values.get("document_number"):
            registration["document_number"] = values["document_number"]
        if values.get("registration_date"):
            registration["date"] = values["registration_date"]
        if values.get("document_type_code"):
            registration["document_type_code"] = values["document_type_code"]
        if values.get("document_type_name"):
            registration["document_type_name"] = values["document_type_name"]
        if values.get("document_type_print_text"):
            registration["document_type_print_text"] = values["document_type_print_text"]
        if values.get("registration_value") is not None:
            registration["value"] = values["registration_value"]
        if values.get("consideration_amount") is not None:
            registration["consideration_amount"] = values["consideration_amount"]
        if values.get("consideration_text"):
            registration["consideration_text"] = values["consideration_text"]
        if values.get("order_number"):
            self.order_number = str(values["order_number"])

    def _handle_parcel(self, values: Dict[str, Any]) -> None:
        sequence = values.get("sequence") or (len(self.title["parcels"]) + 1)
        parcel = {
            "sequence": sequence,
            "linc_number": values.get("linc_number"),
            "short_legal_type": values.get("short_legal_type") or "ATS",
            "short_legal": values.get("short_legal"),
            "legal_text": [],
            "rights_text": [],
        }
        if values.get("short_legal") and not self.title["short_legal_description"]:
            self.title["short_legal_description"] = values["short_legal"][:40]
        self.title["parcels"].append(parcel)
        self._current_parcel = parcel

    def _handle_legal_line(self, values: Dict[str, Any]) -> None:
        if not self._current_parcel:
            return
        line = values.get("text")
        if line:
            self._current_parcel.setdefault("legal_text", []).append(line)

    def _handle_rights_line(self, values: Dict[str, Any]) -> None:
        if not self._current_parcel:
            return
        line = values.get("text")
        if line:
            self._current_parcel.setdefault("rights_text", []).append(line)

    def _owner_group_key(self, tenancy: Optional[str], interest: Optional[str]) -> Tuple[str, Optional[str]]:
        tenancy_key = tenancy or "Common"
        interest_key = interest.strip() if isinstance(interest, str) else interest
        return tenancy_key, interest_key

    def _ensure_owner_group(self, tenancy: Optional[str], interest: Optional[str]) -> Dict[str, Any]:
        key = self._owner_group_key(tenancy, interest)
        if key not in self._owner_groups:
            group = {
                "sequence": len(self._owner_order) + 1,
                "tenancy_type": tenancy,
                "interest": interest,
                "parties": [],
            }
            self._owner_groups[key] = group
            self._owner_order.append(key)
        return self._owner_groups[key]

    def _handle_owner(self, values: Dict[str, Any]) -> None:
        group = self._ensure_owner_group(values.get("tenancy"), values.get("interest"))
        party = {
            "sequence": values.get("sequence") or (len(group["parties"]) + 1),
            "name": values.get("name"),
            "type": values.get("party_type") or "Individual",
            "occupation": values.get("occupation"),
            "role": values.get("role"),
            "aliases": [],
            "address_lines": [],
            "province": None,
            "postal_code": None,
        }
        group["parties"].append(party)
        self._current_owner_party = party

    def _handle_owner_alias(self, values: Dict[str, Any]) -> None:
        if not self._current_owner_party:
            return
        alias = values.get("alias")
        if alias:
            self._current_owner_party.setdefault("aliases", []).append(alias)

    def _handle_owner_address(self, values: Dict[str, Any]) -> None:
        if not self._current_owner_party:
            return
        address_line = values.get("address_line")
        if address_line:
            self._current_owner_party.setdefault("address_lines", []).append(address_line)
        if values.get("province"):
            self._current_owner_party["province"] = values["province"]
        if values.get("postal_code"):
            self._current_owner_party["postal_code"] = values["postal_code"]

    def _handle_instrument(self, values: Dict[str, Any]) -> None:
        self._instrument_sequence += 1
        instrument = {
            "sequence": self._instrument_sequence,
            "registration_number": values.get("registration_number"),
            "formatted_registration_number": values.get("formatted_registration_number")
            or _format_registration_number(values.get("registration_number")),
            "registration_date": values.get("registration_date"),
            "document_type_code": values.get("document_type_code"),
            "document_type_name": values.get("document_type_name"),
            "document_type_print_text": None,
            "discharge_date": values.get("discharge_date"),
            "value": values.get("value"),
            "remarks": [],
        }
        initial_remark = values.get("remarks")
        if initial_remark:
            instrument["remarks"].append(initial_remark)
        self.title["instruments"].append(instrument)
        self._current_instrument = instrument

    def _handle_instrument_remark(self, values: Dict[str, Any]) -> None:
        if not self._current_instrument:
            return
        remark = values.get("text")
        if remark:
            self._current_instrument.setdefault("remarks", []).append(remark)

    def _handle_municipal_address(self, values: Dict[str, Any]) -> None:
        line = values.get("address_line")
        if line:
            self.title.setdefault("municipal_address", []).append(line)

    def consume_line(self, line: str) -> None:
        stripped = line.rstrip("\n\r")
        if not stripped.strip():
            return
        for record in self.mapping.records:
            parsed = record.try_parse(stripped)
            if parsed is None:
                continue
            handler = self._record_handler(record.record_id)
            if handler:
                handler(parsed)
            return

    def _record_handler(self, record_id: str):
        return {
            "TITLE_HEADER": self._handle_title_header,
            "PARCEL": self._handle_parcel,
            "LEGAL_LINE": self._handle_legal_line,
            "RIGHTS_LINE": self._handle_rights_line,
            "OWNER": self._handle_owner,
            "OWNER_ALIAS": self._handle_owner_alias,
            "OWNER_ADDRESS": self._handle_owner_address,
            "INSTRUMENT": self._handle_instrument,
            "INSTRUMENT_REMARK": self._handle_instrument_remark,
            "MUNICIPAL_ADDRESS": self._handle_municipal_address,
        }.get(record_id)

    # ------------------------------------------------------------------
    def _finalize(self) -> Dict[str, Any]:
        title = self.title
        if not title.get("title_number"):
            raise ValueError("ASCII file missing title number (TITLE_HEADER record).")
        if not title.get("formatted_title_number"):
            title["formatted_title_number"] = _format_title_number(title.get("title_number"))
        if not title.get("rights_type"):
            raise ValueError("Rights type missing; update mapping defaults or input data.")
        if not title.get("create_date"):
            raise ValueError("Create date missing from TITLE_HEADER record.")

        registration = title["registration"]
        if not registration.get("document_number"):
            raise ValueError("Registration document number missing from ASCII input.")
        if not registration.get("date"):
            registration["date"] = title.get("create_date")
        if not registration.get("document_type_code") or not registration.get("document_type_name"):
            raise ValueError("Registration document type information missing from ASCII input.")

        owners: List[Dict[str, Any]] = []
        for key in self._owner_order:
            group = self._owner_groups[key]
            parties = sorted(group["parties"], key=lambda p: p.get("sequence", 0))
            owners.append(
                {
                    "tenancy_type": group.get("tenancy_type"),
                    "interest": group.get("interest"),
                    "parties": parties,
                }
            )
        title["owners"] = owners

        for instrument in title["instruments"]:
            remarks = [remark for remark in instrument.get("remarks", []) if remark]
            instrument["document_type_print_text"] = " ".join(remarks) if remarks else None

        parcels = sorted(title["parcels"], key=lambda p: p.get("sequence", 0))
        title["parcels"] = parcels

        return {
            "order_number": self.order_number,
            "title": title,
        }


def _subelement(parent: etree._Element, tag: str, text: Optional[Any] = None) -> etree._Element:
    elem = etree.SubElement(parent, tag)
    if text is not None:
        elem.text = str(text)
    return elem


def build_document_tree(document: Dict[str, Any]) -> etree._Element:
    root = etree.Element("ProductTitleResult")
    order = etree.SubElement(root, "Order")
    order_number = document.get("order_number")
    if order_number is None:
        raise ValueError("Order number missing from ASCII input (TITLE_HEADER order_number).")
    _subelement(order, "OrderNumber", order_number)

    title_data = etree.SubElement(root, "TitleData")
    title_node = etree.SubElement(title_data, "Title")
    title_info = document["title"]

    _subelement(title_node, "TitleNumber", title_info["title_number"])
    if title_info.get("formatted_title_number"):
        _subelement(title_node, "FormattedTitleNumber", title_info["formatted_title_number"])
    _subelement(title_node, "Type", title_info.get("type", "Title"))
    _subelement(title_node, "RightsType", title_info["rights_type"])
    _subelement(title_node, "Consolidated", _bool_text(title_info.get("consolidated", False)))
    _subelement(title_node, "CreateDate", title_info["create_date"])
    if title_info.get("expiry_date"):
        _subelement(title_node, "ExpiryDate", title_info["expiry_date"])
    if title_info.get("short_legal_description"):
        _subelement(title_node, "ShortLegalDescription", title_info["short_legal_description"])
    if title_info.get("estate"):
        _subelement(title_node, "Estate", title_info["estate"])

    municipality = title_info.get("municipality") or {}
    if municipality.get("code") or municipality.get("name"):
        municipality_el = etree.SubElement(title_node, "Municipality")
        _subelement(municipality_el, "Code", municipality.get("code"))
        if municipality.get("name"):
            _subelement(municipality_el, "Name", municipality.get("name"))

    registration = title_info["registration"]
    registration_el = etree.SubElement(title_node, "RegistrationDetails")
    _subelement(registration_el, "DocumentNumber", registration["document_number"])
    _subelement(registration_el, "Date", registration["date"])
    doc_type_el = etree.SubElement(registration_el, "DocumentType")
    _subelement(doc_type_el, "Code", registration["document_type_code"])
    _subelement(doc_type_el, "Name", registration["document_type_name"])
    if registration.get("document_type_print_text"):
        _subelement(doc_type_el, "PrintText", registration["document_type_print_text"])
    if registration.get("value") is not None:
        _subelement(registration_el, "Value", registration["value"])
    if registration.get("consideration_amount") is not None:
        _subelement(registration_el, "ConsiderationAmount", registration["consideration_amount"])
    elif registration.get("consideration_text"):
        _subelement(registration_el, "ConsiderationText", registration["consideration_text"])

    parcels_el = etree.SubElement(title_node, "Parcels")
    for parcel in title_info.get("parcels", []):
        parcel_el = etree.SubElement(parcels_el, "Parcel")
        _subelement(parcel_el, "LINCNumber", parcel.get("linc_number"))
        _subelement(parcel_el, "ShortLegalType", parcel.get("short_legal_type", "ATS"))
        _subelement(parcel_el, "ShortLegal", parcel.get("short_legal"))
        if parcel.get("legal_text"):
            legal_el = etree.SubElement(parcel_el, "LegalText")
            for line in parcel.get("legal_text", []):
                _subelement(legal_el, "TextLine", line)
        if parcel.get("rights_text"):
            rights_el = etree.SubElement(parcel_el, "RightsText")
            text_lines = etree.SubElement(rights_el, "TextLines")
            for line in parcel.get("rights_text", []):
                _subelement(text_lines, "TextLine", line)

    owners_list = title_info.get("owners", [])
    if owners_list:
        owners_el = etree.SubElement(title_node, "Owners")
        for group in owners_list:
            tenancy_el = etree.SubElement(owners_el, "TenancyGroup")
            if group.get("tenancy_type"):
                _subelement(tenancy_el, "TenancyType", group.get("tenancy_type"))
            if group.get("interest"):
                _subelement(tenancy_el, "Interest", group.get("interest"))
            parties_el = etree.SubElement(tenancy_el, "Parties")
            for party in group.get("parties", []):
                party_el = etree.SubElement(parties_el, "Party")
                _subelement(party_el, "Name", party.get("name"))
                if party.get("aliases"):
                    aliases_el = etree.SubElement(party_el, "Aliases")
                    for alias in party.get("aliases", []):
                        _subelement(aliases_el, "Alias", alias)
                if party.get("occupation"):
                    _subelement(party_el, "Occupation", party.get("occupation"))
                address_lines = party.get("address_lines") or []
                if address_lines or party.get("province") or party.get("postal_code"):
                    address_el = etree.SubElement(party_el, "Address")
                    if address_lines:
                        sac_el = etree.SubElement(address_el, "StreetAndCity")
                        for line in address_lines:
                            _subelement(sac_el, "AddressLine", line)
                    if party.get("province"):
                        _subelement(address_el, "Province", party.get("province"))
                    if party.get("postal_code"):
                        _subelement(address_el, "PostalCode", party.get("postal_code"))
                _subelement(party_el, "Type", party.get("type", "Individual"))
                if party.get("role"):
                    _subelement(party_el, "Role", party.get("role"))

    instruments = title_info.get("instruments", [])
    if instruments:
        insts_el = etree.SubElement(title_node, "Instruments")
        for instrument in instruments:
            inst_el = etree.SubElement(insts_el, "Instrument")
            _subelement(inst_el, "RegistrationNumber", instrument.get("registration_number"))
            if instrument.get("formatted_registration_number"):
                _subelement(inst_el, "FormattedRegistrationNumber", instrument.get("formatted_registration_number"))
            if instrument.get("registration_date"):
                _subelement(inst_el, "RegistrationDate", instrument.get("registration_date"))
            if instrument.get("discharge_date"):
                _subelement(inst_el, "DischargeDate", instrument.get("discharge_date"))
            doc_type_el = etree.SubElement(inst_el, "DocumentType")
            _subelement(doc_type_el, "Code", instrument.get("document_type_code"))
            _subelement(doc_type_el, "Name", instrument.get("document_type_name"))
            if instrument.get("document_type_print_text"):
                _subelement(doc_type_el, "PrintText", instrument.get("document_type_print_text"))
            if instrument.get("value") is not None:
                _subelement(inst_el, "Value", instrument.get("value"))

    return root


def parse_ascii_to_xml(ascii_text: str, mapping_path: str) -> str:
    """Parse SPIN 2 ASCII content into canonical XML.

    Parameters
    ----------
    ascii_text:
        The raw fixed-width ASCII content.
    mapping_path:
        Path to the YAML mapping file that defines record layouts.
    """

    mapping = _load_mapping(mapping_path)
    parser = Spin2AsciiParser(mapping)

    for line in ascii_text.splitlines():
        parser.consume_line(line)

    document = parser._finalize()
    xml_root = build_document_tree(document)
    return etree.tostring(xml_root, pretty_print=True, encoding="utf-8").decode("utf-8")
