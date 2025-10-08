"""Template composition engine for absolute PDF layout."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree
class XPathBinder:
    def __init__(self, root: etree._Element):
        self.root = root

    def eval_string(self, expr: str) -> str:
        if not expr:
            return ""
        try:
            result = self.root.xpath(expr)
        except Exception:
            return ""
        if isinstance(result, list):
            if not result:
                return ""
            if isinstance(result[0], etree._Element):
                return "".join((node.text or "") for node in result)
            return str(result[0])
        if isinstance(result, etree._Element):
            return result.text or ""
        return str(result)

    def eval_nodes(self, expr: str) -> List[etree._Element]:
        if not expr:
            return []
        try:
            result = self.root.xpath(expr)
        except Exception:
            return []
        if isinstance(result, list):
            return [node for node in result if isinstance(node, etree._Element)]
        if isinstance(result, etree._Element):
            return [result]
        return []


def _measure_text(text: str, font: str, size: float) -> float:
    try:
        from reportlab.pdfbase import pdfmetrics
    except ImportError:  # pragma: no cover - dependency guard
        raise RuntimeError("ReportLab is required for template composition")

    try:
        return pdfmetrics.stringWidth(text, font, size)
    except Exception:
        return pdfmetrics.stringWidth(text, "Helvetica", size)


def _find_split_index(word: str, width: float, font: str, size: float) -> int:
    for idx in range(len(word) - 1, 1, -1):
        segment = word[:idx] + "-"
        if _measure_text(segment, font, size) <= width:
            return idx
    return max(1, len(word) - 1)


def _split_long_word(word: str, width: float, font: str, size: float, hyphenate: bool) -> List[str]:
    if not hyphenate or not word:
        return [word]
    remainder = word
    segments: List[str] = []
    while _measure_text(remainder, font, size) > width and len(remainder) > 1:
        split_idx = _find_split_index(remainder, width, font, size)
        segments.append(remainder[:split_idx] + "-")
        remainder = remainder[split_idx:]
    segments.append(remainder)
    return segments


def wrap_text(
    text: str,
    width: float,
    font: str,
    size: float,
    hyphenate: bool = True,
) -> List[str]:
    paragraphs = text.replace("\r", "").split("\n") or [""]
    lines: List[str] = []
    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words.pop(0)
        while words:
            next_word = words.pop(0)
            candidate = f"{current} {next_word}" if current else next_word
            if _measure_text(candidate, font, size) <= width:
                current = candidate
                continue
            if not current:
                segments = _split_long_word(next_word, width, font, size, hyphenate)
                lines.extend(segments[:-1])
                current = segments[-1]
            else:
                lines.append(current)
                current = next_word
        # Final word handling for the paragraph
        if _measure_text(current, font, size) <= width:
            lines.append(current)
        else:
            segments = _split_long_word(current, width, font, size, hyphenate)
            lines.extend(segments)
    return lines


def apply_ellipsis(line: str, width: float, font: str, size: float) -> str:
    ellipsis = "..."
    if not line:
        return ellipsis
    while line and _measure_text(line + ellipsis, font, size) > width:
        line = line[:-1]
    return (line + ellipsis) if line else ellipsis


@dataclass
class BaselineGrid:
    leading: float
    offset: float

    def align(self, baseline: float) -> float:
        if self.leading <= 0:
            return baseline
        if baseline <= self.offset:
            return self.offset
        steps = round((baseline - self.offset) / self.leading)
        return self.offset + steps * self.leading


class LayoutContext:
    def __init__(
        self,
        page_width: float,
        page_height: float,
        margins: Dict[str, float],
        baseline_grid: Optional[BaselineGrid] = None,
    ) -> None:
        self.page_width = page_width
        self.page_height = page_height
        self.margins = {
            "l": margins.get("l", 36),
            "r": margins.get("r", 36),
            "t": margins.get("t", 36),
            "b": margins.get("b", 36),
        }
        self.baseline_grid = baseline_grid
        self.pages: List[List[Dict[str, Any]]] = [[]]

    def new_page(self) -> None:
        self.pages.append([])

    @property
    def current_page(self) -> List[Dict[str, Any]]:
        return self.pages[-1]

    def add_op(self, op: Dict[str, Any]) -> None:
        self.current_page.append(op)

    def tl_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        return x, self.page_height - y

    def baseline_to_canvas(self, baseline_from_top: float) -> float:
        aligned = (
            self.baseline_grid.align(baseline_from_top)
            if self.baseline_grid
            else baseline_from_top
        )
        return self.page_height - aligned

    @property
    def bottom_limit(self) -> float:
        return self.page_height - self.margins["b"]


class ElementComposer:
    def __init__(self, context: LayoutContext, binder: XPathBinder):
        self.ctx = context
        self.binder = binder

    # ------------------------------------------------------------------
    def compose(self, element: Dict[str, Any]) -> None:
        etype = element.get("type")
        if etype == "StaticText":
            self._compose_text_line(element, element.get("text", ""))
        elif etype == "DynamicText":
            value = self.binder.eval_string(element.get("binding", ""))
            self._compose_text_line(element, value)
        elif etype == "TextBox":
            value = element.get("text")
            if value is None:
                value = self.binder.eval_string(element.get("binding", ""))
            self._compose_text_box(element, value)
        elif etype == "Image":
            self._compose_image(element)
        elif etype == "Rule":
            self._compose_rule(element)
        elif etype == "RepeatingTable":
            self._compose_repeating_table(element)

    # ------------------------------------------------------------------
    def _compose_text_line(self, element: Dict[str, Any], text: str) -> None:
        font = element.get("font", "Helvetica")
        size = element.get("size", 10)
        align = element.get("align", "left")
        x = element.get("x", self.ctx.margins["l"])
        y = element.get("y", self.ctx.margins["t"])
        max_width = element.get("max_width")

        if max_width is not None and max_width > 0:
            if _measure_text(text, font, size) > max_width:
                text = apply_ellipsis(text, max_width, font, size)

        canvas_x, canvas_y = self.ctx.tl_to_canvas(x, y)
        op = {
            "op": "text",
            "text": text,
            "x": canvas_x,
            "y": canvas_y,
            "font": font,
            "size": size,
            "align": align,
        }
        if max_width is not None:
            op["width"] = max_width
        if element.get("tab_leader"):
            op["tab_leader"] = element.get("tab_leader")
            op["leader_target_x"] = element.get("leader_target_x")
        self.ctx.add_op(op)

    # ------------------------------------------------------------------
    def _compose_text_box(self, element: Dict[str, Any], text: str) -> None:
        font = element.get("font", "Helvetica")
        size = element.get("size", 10)
        leading = element.get("leading", size * 1.2)
        hyphenate = element.get("hyphenate", True)
        align = element.get("align", "left")
        ellipsis = element.get("ellipsis", True)
        width = element.get("width")
        height = element.get("height")
        if not width or not height:
            return

        padding_top = element.get("padding_top", 0)
        padding_left = element.get("padding_left", 0)
        padding_right = element.get("padding_right", 0)

        effective_width = max(0.0, width - (padding_left + padding_right))
        wrapped_lines = wrap_text(text or "", effective_width, font, size, hyphenate=hyphenate)

        max_lines = max(1, int((height - padding_top) / leading))
        if len(wrapped_lines) > max_lines:
            truncated = wrapped_lines[:max_lines]
            if ellipsis and truncated:
                truncated[-1] = apply_ellipsis(truncated[-1], effective_width, font, size)
            wrapped_lines = truncated

        base_top = element.get("y", self.ctx.margins["t"]) + padding_top + size
        x_base = element.get("x", self.ctx.margins["l"]) + padding_left

        for idx, line in enumerate(wrapped_lines):
            baseline = base_top + idx * leading
            canvas_y = self.ctx.baseline_to_canvas(baseline)
            op = {
                "op": "text",
                "text": line,
                "x": x_base,
                "y": canvas_y,
                "font": font,
                "size": size,
                "align": align,
                "width": effective_width,
            }
            self.ctx.add_op(op)

    # ------------------------------------------------------------------
    def _compose_image(self, element: Dict[str, Any]) -> None:
        path = element.get("path")
        if not path:
            return
        width = element.get("width")
        height = element.get("height")
        if not width or not height:
            return
        x, y = element.get("x", self.ctx.margins["l"]), element.get("y", self.ctx.margins["t"])
        canvas_x, canvas_y = self.ctx.tl_to_canvas(x, y + height)
        self.ctx.add_op(
            {
                "op": "image",
                "path": path,
                "x": canvas_x,
                "y": canvas_y,
                "width": width,
                "height": height,
            }
        )

    # ------------------------------------------------------------------
    def _compose_rule(self, element: Dict[str, Any]) -> None:
        x1, y1 = self.ctx.tl_to_canvas(element.get("x1", 0), element.get("y1", 0))
        x2, y2 = self.ctx.tl_to_canvas(element.get("x2", 0), element.get("y2", 0))
        self.ctx.add_op(
            {
                "op": "line",
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "width": element.get("width", 0.5),
            }
        )

    # ------------------------------------------------------------------
    def _compose_repeating_table(self, element: Dict[str, Any]) -> None:
        binding = element.get("binding")
        rows = self.binder.eval_nodes(binding)
        if not rows:
            return

        columns = element.get("columns", [])
        if not columns:
            return

        x_origin = element.get("x", self.ctx.margins["l"])
        y_origin = element.get("y", self.ctx.margins["t"])
        padding = element.get("padding", {})
        padding_top = padding.get("top", 2)
        padding_bottom = padding.get("bottom", 2)
        padding_left = padding.get("left", 2)
        padding_right = padding.get("right", 2)

        header_font = element.get("header_font", "Helvetica-Bold")
        header_size = element.get("header_size", 9)
        header_leading = element.get("header_leading", header_size * 1.2)
        row_font = element.get("row_font", "Helvetica")
        row_size = element.get("row_size", 9)
        row_leading = element.get("row_leading", row_size * 1.2)

        column_widths = [col.get("width", 60) for col in columns]
        col_aligns = [col.get("align", "left") for col in columns]
        col_bindings = [col.get("binding") for col in columns]
        header_gap = element.get("header_gap", row_leading)

        def render_header(page_index: int) -> None:
            baseline = self.ctx.baseline_to_canvas(y_origin + header_leading)
            x_cursor = x_origin
            for idx, column in enumerate(columns):
                width = column_widths[idx]
                header_text = column.get("header", "")
                self.ctx.add_op(
                    {
                        "op": "text",
                        "text": header_text,
                        "x": x_cursor + padding_left,
                        "y": baseline,
                        "font": header_font,
                        "size": header_size,
                        "align": col_aligns[idx],
                        "width": width - (padding_left + padding_right),
                    }
                )
                x_cursor += width

        def render_row(row_node: etree._Element, row_index: int, y_start: float) -> float:
            cell_lines: List[List[str]] = []
            max_lines = 1
            for width, binding in zip(column_widths, col_bindings):
                if not binding:
                    text_value = ""
                elif binding.startswith("/"):
                    text_value = self.binder.eval_string(binding)
                else:
                    expr = binding if binding.startswith(".") else f"./{binding}"
                    value = row_node.xpath(expr)
                    if isinstance(value, list):
                        norm = [v if isinstance(v, str) else getattr(v, "text", "") for v in value]
                        text_value = " ".join(filter(None, norm))
                    else:
                        text_value = str(value)
                lines = wrap_text(
                    text_value,
                    width - (padding_left + padding_right),
                    row_font,
                    row_size,
                )
                cell_lines.append(lines)
                max_lines = max(max_lines, len(lines))

            row_height = max_lines * row_leading + padding_top + padding_bottom
            if y_start + row_height > self.ctx.bottom_limit:
                self.ctx.new_page()
                render_header(len(self.ctx.pages) - 1)
                y_start = y_origin + header_leading + header_gap

            x_cursor = x_origin
            for col_idx, lines in enumerate(cell_lines):
                for line_idx, line in enumerate(lines):
                    baseline = y_start + padding_top + (line_idx * row_leading) + row_size
                    canvas_y = self.ctx.baseline_to_canvas(baseline)
                    self.ctx.add_op(
                        {
                            "op": "text",
                            "text": line,
                            "x": x_cursor + padding_left,
                            "y": canvas_y,
                            "font": row_font,
                            "size": row_size,
                            "align": col_aligns[col_idx],
                            "width": column_widths[col_idx] - (padding_left + padding_right),
                        }
                    )
                x_cursor += column_widths[col_idx]
            return y_start + row_height

        render_header(0)
        y_cursor = y_origin + header_leading + header_gap
        for idx, node in enumerate(rows):
            y_cursor = render_row(node, idx, y_cursor)


def compose(template: Dict[str, Any], xml_root: etree._Element) -> List[List[Dict[str, Any]]]:
    page_config = template.get("page", {})
    page_width = page_config.get("width", 612)
    page_height = page_config.get("height", 792)
    margins = page_config.get("margins", {})
    baseline_conf = page_config.get("baseline", {})
    baseline_grid = None
    if baseline_conf:
        leading = baseline_conf.get("leading")
        offset = baseline_conf.get("offset", margins.get("t", 36))
        if leading:
            baseline_grid = BaselineGrid(leading=leading, offset=offset)

    context = LayoutContext(page_width, page_height, margins, baseline_grid)
    binder = XPathBinder(xml_root)
    composer = ElementComposer(context, binder)

    for element in template.get("elements", []):
        composer.compose(element)

    return context.pages
