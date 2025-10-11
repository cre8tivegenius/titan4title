from datetime import date
from decimal import Decimal

import pytest
from lxml import etree

pytest.importorskip("yaml")

from app.services import title_request_builder


def _names_from_xml(xml_str: str):
    root = etree.fromstring(xml_str.encode("utf-8"))
    return root.xpath("/ProductTitleResult/TitleData/Title/Owners/TenancyGroup/Parties/Party/Name/text()")


def test_builds_multi_party_group():
    build = title_request_builder.build_new_title_xml(
        reference_number="REQ-2025-1002",
        buyer_name="Andre Yves Lacroix",
        purchase_price=Decimal("650000.00"),
        purchase_date=date(2025, 10, 8),
        legal_description="PLAN 0723943 BLOCK 86 LOT 31 EXCEPTING THEREOUT ALL MINES AND MINERALS",
        municipality_name="CITY OF EDMONTON",
        owner_groups=[
            {
                "tenancy_type": "Joint Tenants",
                "interest": "100%",
                "parties": [
                    {"name": "Andre Yves Lacroix"},
                    {"name": "Marie-Claude Bouchard"},
                ],
            }
        ],
    )

    names = _names_from_xml(build.xml)
    assert names == ["Andre Yves Lacroix", "Marie-Claude Bouchard"]
    assert build.title_number
    assert build.registration_number
