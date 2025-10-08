from lxml import etree
from typing import Any, Dict, List, Tuple

class XPathBinder:
    def __init__(self, root: etree._Element):
        self.root = root
    def eval_string(self, expr: str) -> str:
        try:
            res = self.root.xpath(expr)
            if isinstance(res, list):
                if len(res)==0:
                    return ""
                if isinstance(res[0], etree._Element):
                    return "".join([r.text or "" for r in res])
                return str(res[0])
            return str(res)
        except Exception:
            return ""
    def eval_nodes(self, expr: str) -> List[Any]:
        try:
            res = self.root.xpath(expr)
            return res if isinstance(res, list) else [res]
        except Exception:
            return []

def compose(template: Dict[str, Any], xml_root: etree._Element) -> List[Dict[str, Any]]:
    """Return a list of pages, each page is a list of draw ops (dicts)."""
    binder = XPathBinder(xml_root)
    page_w = template.get("page", {}).get("width", 612)
    page_h = template.get("page", {}).get("height", 792)
    ops_pages: List[List[Dict[str, Any]]] = [[]]
    cursor_y = 0  # not used for absolute layout except for tables
    elements = template.get("elements", [])

    def current_page(): return ops_pages[-1]
    def new_page(): ops_pages.append([])

    # Helper: convert top-left coords to reportlab (bottom-left)
    def tl(x, y):
        return x, page_h - y

    for el in elements:
        et = el.get("type")
        if et in ("StaticText", "DynamicText"):
            text = el.get("text", "") if et=="StaticText" else binder.eval_string(el.get("binding", ""))
            x, y = tl(el.get("x", 0), el.get("y", 0))
            op = {"op":"text", "text":text, "x":x, "y":y, "font":el.get("font","Helvetica"),
                  "size": el.get("size", 10), "align": el.get("align","left"), "max_width": el.get("max_width")}
            current_page().append(op)
        elif et == "Image":
            x, y = tl(el.get("x", 0), el.get("y", 0) + el.get("height",0))  # y provided as top-left
            op = {"op":"image", "path": el.get("path"), "x":x, "y":y, "width": el.get("width"),
                  "height": el.get("height")}
            current_page().append(op)
        elif et == "Rule":
            x1, y1 = tl(el.get("x1",0), el.get("y1",0))
            x2, y2 = tl(el.get("x2",0), el.get("y2",0))
            op = {"op":"line", "x1":x1, "y1":y1, "x2":x2, "y2":y2, "width": el.get("width", 0.5)}
            current_page().append(op)
        elif et == "RepeatingTable":
            binding = el.get("binding")
            rows = binder.eval_nodes(binding)
            x = el.get("x", 0)
            y = el.get("y", 0)
            row_h = el.get("row_height", 12)
            colspec = el.get("columns", [])
            header = [c.get("header","") for c in colspec]
            widths = [c.get("width", 60) for c in colspec]
            # Header
            hx, hy = tl(x, y)
            # Emit header
            cur = current_page()
            xpos = x
            for i, head in enumerate(header):
                tx, ty = tl(xpos, y)
                cur.append({"op":"text","text":head,"x":tx,"y":ty,"font":el.get("header_font","Helvetica-Bold"),"size":el.get("header_size",10)})
                xpos += widths[i]
            # Rows
            y_cursor = y + row_h
            for node in rows:
                # Page break if needed
                if y_cursor > (template.get("page", {}).get("height", 792) - 72):  # simplistic bottom margin
                    new_page()
                    # re-emit header on new page
                    xpos = x
                    for i, head in enumerate(header):
                        tx, ty = tl(xpos, y)
                        current_page().append({"op":"text","text":head,"x":tx,"y":ty,"font":el.get("header_font","Helvetica-Bold"),"size":el.get("header_size",10)})
                        xpos += widths[i]
                    y_cursor = y + row_h
                # emit row cells
                xpos = x
                for i, col in enumerate(colspec):
                    expr = col.get("binding","")
                    # bind relative to node if expr starts with '.'
                    value = ""
                    try:
                        if expr.startswith("."):
                            res = node.xpath(expr)
                            if isinstance(res, list):
                                value = " ".join([r.text if hasattr(r,'text') and r.text else str(r) for r in res]) if res else ""
                            else:
                                value = str(res)
                        else:
                            value = node.xpath(expr) if expr else ""
                            if isinstance(value, list):
                                value = " ".join([v if isinstance(v,str) else (v.text or "") for v in value])
                            elif hasattr(value, "text"):
                                value = value.text or ""
                            else:
                                value = str(value)
                    except Exception:
                        value = ""
                    tx, ty = tl(xpos, y_cursor)
                    current_page().append({"op":"text","text":str(value),"x":tx,"y":ty,
                                           "font":el.get("row_font","Helvetica"),
                                           "size":el.get("row_size",10)})
                    xpos += widths[i]
                y_cursor += row_h
        else:
            # unknown element -> ignore
            pass

    return ops_pages
