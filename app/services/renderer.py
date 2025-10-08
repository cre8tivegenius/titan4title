"""PDF renderer implementing deterministic output and PDF/A support."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Dict, List

from lxml import etree

from .template_engine import compose
from .font_registry import register_directory
from app.utils import hashing, pdfa


DEFAULT_TEMPLATE_PATH = Path("app/data/templates")
ASSET_FONT_DIR = Path("app/assets/fonts")
DEFAULT_ICC_PATH = Path("app/assets/icc/sRGB.icc")

INCH = 72.0

DEFAULT_METADATA = {
    "title": "Certificate of Title",
    "author": "Alberta Land Titles",
    "creator": "Title Document Creator Pro",
    "producer": "Title Document Creator Pro",
    "created": "D:20240101000000Z",
    "modified": "D:20240101000000Z",
}


def _load_template(template_id: str) -> Dict[str, object]:
    template_path = DEFAULT_TEMPLATE_PATH / f"{template_id}.json"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return json.loads(template_path.read_text(encoding="utf-8"))


def _resolve_font(alias_map: Dict[str, str], font_name: str) -> str:
    return alias_map.get(font_name, font_name)


def _draw_justified(canvas_obj, text: str, x: float, y: float, width: float, font: str, size: float) -> None:
    from reportlab.pdfbase import pdfmetrics

    words = text.split()
    if len(words) <= 1:
        canvas_obj.drawString(x, y, text)
        return

    total_text_width = sum(pdfmetrics.stringWidth(word, font, size) for word in words)
    spaces = len(words) - 1
    space_width = pdfmetrics.stringWidth(" ", font, size)
    extra_space = max(0.0, width - total_text_width - (spaces * space_width))
    additional = extra_space / spaces if spaces else 0

    cursor = x
    for idx, word in enumerate(words):
        canvas_obj.drawString(cursor, y, word)
        cursor += pdfmetrics.stringWidth(word, font, size)
        if idx < spaces:
            cursor += space_width + additional


def _draw_text_op(canvas_obj, op: Dict[str, object], alias_map: Dict[str, str]) -> None:
    from reportlab.pdfbase import pdfmetrics

    font = _resolve_font(alias_map, op.get("font", "Helvetica"))
    size = float(op.get("size", 10))
    text = op.get("text", "")
    if not isinstance(text, str):
        text = str(text)
    x = float(op.get("x", 0.0))
    y = float(op.get("y", 0.0))
    align = op.get("align", "left")
    width = op.get("width")

    canvas_obj.setFont(font, size)
    if align == "right":
        canvas_obj.drawRightString(x, y, text)
    elif align == "center":
        canvas_obj.drawCentredString(x, y, text)
    elif align == "justify" and width:
        _draw_justified(canvas_obj, text, x, y, float(width), font, size)
    else:
        canvas_obj.drawString(x, y, text)

    leader = op.get("tab_leader")
    leader_target = op.get("leader_target_x")
    if leader and leader_target:
        leader_spacing = pdfmetrics.stringWidth(leader, font, size)
        cursor = x + pdfmetrics.stringWidth(text, font, size)
        while cursor < leader_target:
            canvas_obj.drawString(cursor, y, leader)
            cursor += leader_spacing


def _draw_line_op(canvas_obj, op: Dict[str, object]) -> None:
    canvas_obj.setLineWidth(float(op.get("width", 0.5)))
    canvas_obj.line(float(op.get("x1", 0.0)), float(op.get("y1", 0.0)), float(op.get("x2", 0.0)), float(op.get("y2", 0.0)))


def _draw_image_op(canvas_obj, op: Dict[str, object]) -> None:
    from reportlab.lib.utils import ImageReader
    path = op.get("path")
    if not path:
        return
    try:
        image_reader = ImageReader(path)
        canvas_obj.drawImage(
            image_reader,
            float(op.get("x", 0.0)),
            float(op.get("y", 0.0)),
            width=float(op.get("width", 0.0)),
            height=float(op.get("height", 0.0)),
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        pass


def _draw_operations(canvas_obj, operations: List[Dict[str, object]], alias_map: Dict[str, str]) -> None:
    for op in operations:
        optype = op.get("op")
        if optype == "text":
            _draw_text_op(canvas_obj, op, alias_map)
        elif optype == "line":
            _draw_line_op(canvas_obj, op)
        elif optype == "image":
            _draw_image_op(canvas_obj, op)


def _apply_metadata(canvas_obj, metadata: Dict[str, str], document_id: str) -> None:
    info = canvas_obj._doc.info
    info.title = metadata.get("title", DEFAULT_METADATA["title"])
    info.author = metadata.get("author", DEFAULT_METADATA["author"])
    info.creator = metadata.get("creator", DEFAULT_METADATA["creator"])
    info.producer = metadata.get("producer", DEFAULT_METADATA["producer"])
    creation = metadata.get("created", DEFAULT_METADATA["created"])
    modified = metadata.get("modified", creation)
    info.creationDate = creation
    info.modDate = modified
    canvas_obj.setTitle(info.title)
    canvas_obj.setAuthor(info.author)
    canvas_obj.setCreator(info.creator)
    canvas_obj._doc._ID = (document_id, document_id)


def _generate_qr_image(data: str):
    try:
        import qrcode
    except ImportError:  # pragma: no cover - dependency guard
        return None

    qr = qrcode.QRCode(version=6, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=2, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    from reportlab.lib.utils import ImageReader

    return ImageReader(buffer)


def render(xml_str: str, template_id: str = "alberta_title_v1", options: Dict[str, object] | None = None) -> bytes:
    try:
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("ReportLab is required to render PDFs") from exc
    options = options or {}
    xml_root = etree.fromstring(xml_str.encode("utf-8"))
    template = _load_template(template_id)

    alias_map = register_directory(str(ASSET_FONT_DIR))

    pages = compose(template, xml_root)
    page_conf = template.get("page", {})
    page_width = page_conf.get("width", 612)
    page_height = page_conf.get("height", 792)

    buffer = io.BytesIO()
    canvas_obj = rl_canvas.Canvas(buffer, pagesize=(page_width, page_height))

    xml_hash = hashing.sha256_hex(xml_str.encode("utf-8"))
    metadata = {**DEFAULT_METADATA, **options.get("metadata", {})}
    _apply_metadata(canvas_obj, metadata, xml_hash)

    qr_conf = page_conf.get(
        "qr",
        {
            "enabled": True,
            "size": 0.9 * INCH,
            "margin_x": 1.4 * INCH,
            "margin_y": 0.6 * INCH,
        },
    )
    qr_reader = None
    if qr_conf.get("enabled", True):
        qr_reader = _generate_qr_image(xml_hash)

    for page_ops in pages:
        _draw_operations(canvas_obj, page_ops, alias_map)
        if qr_reader is not None:
            size = float(qr_conf.get("size", 0.9 * INCH))
            margin_x = float(qr_conf.get("margin_x", 1.4 * INCH))
            margin_y = float(qr_conf.get("margin_y", 0.6 * INCH))
            canvas_obj.drawImage(
                qr_reader,
                page_width - margin_x,
                margin_y,
                width=size,
                height=size,
                preserveAspectRatio=True,
                mask="auto",
            )
        canvas_obj.showPage()

    if options.get("pdfa", True):
        pdfa.apply_pdfa(canvas_obj, str(options.get("icc_path", DEFAULT_ICC_PATH)), metadata)

    canvas_obj.save()
    return buffer.getvalue()
