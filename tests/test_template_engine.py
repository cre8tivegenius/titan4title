from lxml import etree

import pytest

pytest.importorskip("reportlab")

from app.services import template_engine


def test_textbox_wraps_with_ellipsis():
    xml = etree.fromstring("<Doc><Summary>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Pellentesque habitant.</Summary></Doc>")
    template = {
        "page": {
            "width": 200,
            "height": 200,
            "baseline": {"leading": 12, "offset": 20},
        },
        "elements": [
            {
                "type": "TextBox",
                "binding": "string(/Doc/Summary)",
                "x": 20,
                "y": 30,
                "width": 100,
                "height": 36,
                "font": "Helvetica",
                "size": 10,
                "leading": 12,
                "ellipsis": True,
            }
        ],
    }

    pages = template_engine.compose(template, xml)
    assert len(pages) == 1
    text_ops = [op for op in pages[0] if op["op"] == "text"]
    assert len(text_ops) == 3  # height allows only three lines
    assert text_ops[-1]["text"].endswith("...")


def test_repeating_table_spans_pages_and_repeats_header():
    items = "".join(
        f"<Item><Number>{i}</Number><Remark>Remark line for instrument {i}</Remark></Item>"
        for i in range(1, 11)
    )
    xml = etree.fromstring(f"<Doc><Items>{items}</Items></Doc>")
    template = {
        "page": {"width": 240, "height": 320, "margins": {"t": 24, "b": 24}},
        "elements": [
            {
                "type": "RepeatingTable",
                "binding": "/Doc/Items/Item",
                "x": 24,
                "y": 36,
                "columns": [
                    {"header": "No", "binding": "Number", "width": 40},
                    {"header": "Remark", "binding": "Remark", "width": 140},
                ],
                "row_size": 9,
                "row_leading": 11,
                "header_size": 10,
                "header_leading": 12,
                "header_gap": 6,
            }
        ],
    }

    pages = template_engine.compose(template, xml)
    assert len(pages) > 1
    header_count = sum(1 for page in pages for op in page if op.get("text") == "No")
    assert header_count == len(pages)
    # Ensure table content spans both pages
    total_numbers = [op["text"] for page in pages for op in page if op.get("text", "").isdigit()]
    assert "1" in total_numbers and "10" in total_numbers
