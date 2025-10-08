from pathlib import Path

import pytest
from lxml import etree

from app.services import ascii_parser


MAPPING_PATH = "app/data/mappings/alberta_spin2_ascii_v1.yaml"


def _pad(value: str, width: int) -> str:
    return value.ljust(width)[:width]


def _build_minimal_ascii() -> str:
    header = (
        "TH"
        + _pad("002345678901", 12)
        + "S"
        + "N"
        + "20240115"
        + _pad("DOC000012345", 12)
        + _pad("TRFS", 4)
        + _pad("Transfer Of Land", 30)
        + _pad("0000123456", 10)
        + _pad("EDM0", 4)
        + _pad("City Of Edmonton", 30)
        + _pad("Fee Simple", 12)
    )

    parcel = (
        "PL"
        + _pad("1", 3)
        + _pad("0034567890", 10)
        + _pad("ATS", 3)
        + _pad("LOT 1 BLOCK 2 PLAN 2314KS", 60)
    )

    legal = "LG" + _pad("PORTION OF SECTION 23 TOWNSHIP 52", 80)
    rights = "RG" + _pad("AND THE RIGHT TO WORK SAME", 80)

    owner = (
        "OW"
        + _pad("1", 3)
        + _pad("DOE JOHN A", 60)
        + _pad("I", 1)
        + _pad("JT", 4)
        + _pad("1/2", 10)
        + _pad("FARMER", 20)
        + _pad("OWNER", 12)
    )

    owner_alias = "OX" + _pad("JOHN DOE", 60)
    owner_addr = "OA" + _pad("123 MAIN STREET NW", 60) + _pad("Alberta", 20) + _pad("T5J3N5", 10)

    instrument = (
        "IN"
        + _pad("202312345678", 12)
        + " "
        + "20240201"
        + " "
        + _pad("MORT", 4)
        + " "
        + _pad("Mortgage", 30)
        + _pad("Mortgage to Big Bank", 60)
    )
    instrument_remark = "IR" + _pad("Additional covenant applies", 60)

    municipal = "MA" + _pad("123 Main Street NW, Edmonton", 60)

    return "\n".join(
        [
            header,
            parcel,
            legal,
            rights,
            owner,
            owner_alias,
            owner_addr,
            instrument,
            instrument_remark,
            municipal,
        ]
    )


def _build_multi_owner_ascii() -> str:
    base = _build_minimal_ascii().splitlines()

    second_owner = (
        "OW"
        + _pad("2", 3)
        + _pad("ACME HOLDINGS INC.", 60)
        + _pad("C", 1)
        + _pad("CM", 4)
        + _pad("1/2", 10)
        + _pad("", 20)
        + _pad("MORTGAGEE", 12)
    )
    second_address = "OA" + _pad("500 CAPITAL BLVD", 60) + _pad("Alberta", 20) + _pad("T2P1A1", 10)

    second_instrument = (
        "IN"
        + _pad("202312345679", 12)
        + " "
        + "20240512"
        + " "
        + _pad("ASGN", 4)
        + " "
        + _pad("Assignment", 30)
        + _pad("Assigned to ACME", 60)
    )

    base.extend([second_owner, second_address, second_instrument])
    return "\n".join(base)


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def test_ascii_to_xml_basic_structure():
    ascii_text = _build_minimal_ascii()
    xml = ascii_parser.parse_ascii_to_xml(ascii_text, MAPPING_PATH)
    root = _parse(xml)

    title = root.find("TitleData/Title")
    assert title is not None
    assert title.findtext("TitleNumber") == "002345678901"
    assert title.findtext("FormattedTitleNumber") == "002 345 678 901"
    assert title.findtext("RightsType") == "Surface"
    assert title.findtext("Consolidated") == "false"

    registration = title.find("RegistrationDetails")
    assert registration is not None
    assert registration.findtext("DocumentNumber") == "DOC000012345"
    assert registration.findtext("Date") == "2024-01-15"
    assert registration.findtext("DocumentType/Name") == "Transfer Of Land"

    parcel = title.find("Parcels/Parcel")
    assert parcel is not None
    assert parcel.findtext("LINCNumber") == "0034567890"
    legal_lines = parcel.xpath("LegalText/TextLine/text()")
    assert "PORTION OF SECTION 23 TOWNSHIP 52" in legal_lines[0]
    rights_lines = parcel.xpath("RightsText/TextLines/TextLine/text()")
    assert rights_lines == ["AND THE RIGHT TO WORK SAME"]

    tenancy = title.find("Owners/TenancyGroup")
    assert tenancy.findtext("TenancyType") == "Joint Tenants"
    party = tenancy.find("Parties/Party")
    assert party.findtext("Name") == "DOE JOHN A"
    address_lines = party.xpath("Address/StreetAndCity/AddressLine/text()")
    assert address_lines == ["123 MAIN STREET NW"]
    assert party.findtext("Address/Province") == "Alberta"
    assert party.findtext("Address/PostalCode") == "T5J3N5"
    aliases = party.xpath("Aliases/Alias/text()")
    assert aliases == ["JOHN DOE"]

    instrument = title.find("Instruments/Instrument")
    assert instrument.findtext("RegistrationNumber") == "202312345678"
    assert instrument.findtext("RegistrationDate") == "2024-02-01"
    assert instrument.findtext("DocumentType/PrintText") == "Mortgage to Big Bank Additional covenant applies"


def test_ascii_to_xml_multiple_owners_and_instruments():
    ascii_text = _build_multi_owner_ascii()
    xml = ascii_parser.parse_ascii_to_xml(ascii_text, MAPPING_PATH)
    root = _parse(xml)

    tenancy_groups = root.xpath("TitleData/Title/Owners/TenancyGroup")
    assert len(tenancy_groups) == 2
    types = [tg.findtext("TenancyType") for tg in tenancy_groups]
    assert "Joint Tenants" in types and "Common" in types

    parties = root.xpath("TitleData/Title/Owners/TenancyGroup/Parties/Party")
    names = [p.findtext("Name") for p in parties]
    assert "DOE JOHN A" in names
    assert "ACME HOLDINGS INC." in names

    instruments = root.xpath("TitleData/Title/Instruments/Instrument")
    assert len(instruments) == 2
    numbers = [inst.findtext("RegistrationNumber") for inst in instruments]
    assert "202312345678" in numbers
    assert "202312345679" in numbers
    assignment = [inst for inst in instruments if inst.findtext("DocumentType/Name") == "Assignment"]
    assert assignment
    assert assignment[0].findtext("DocumentType/PrintText") == "Assigned to ACME"
