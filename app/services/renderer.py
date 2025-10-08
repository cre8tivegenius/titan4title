from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from lxml import etree
import io, qrcode, hashlib, json, os
from .template_engine import compose
from .font_registry import register_directory

def draw_text(c, text, x, y, font="Helvetica", size=10, align="left", max_width=None):
    c.setFont(font, size)
    if max_width is None:
        if align == "right":
            c.drawRightString(x, y, text)
        elif align == "center":
            c.drawCentredString(x, y, text)
        else:
            c.drawString(x, y, text)
    else:
        # naive single-line truncation with ellipsis
        w = stringWidth(text, font, size)
        if w <= max_width:
            c.drawString(x, y, text)
        else:
            ell = "..."
            while stringWidth(text+ell, font, size) > max_width and len(text)>0:
                text = text[:-1]
            c.drawString(x, y, text+ell)

def render(xml_str: str, template_id: str = "alberta_title_v1", options: dict = None) -> bytes:
    options = options or {}
    root = etree.fromstring(xml_str.encode("utf-8"))
    # Load template JSON
    path = f"app/data/templates/{template_id}.json"
    if not os.path.exists(path):
        # Fallback to minimal header-only template
        tmpl = {
            "page":{"width":612,"height":792},
            "elements":[
                {"type":"StaticText","text":"CERTIFICATE OF TITLE","x":72,"y":744,"font":"Times-Roman","size":12},
                {"type":"DynamicText","binding":"string(/Title/TitleNumber)","x":540,"y":744,"font":"Times-Roman","size":12,"align":"right"}
            ]
        }
    else:
        tmpl = json.load(open(path, "r"))

    # Register local fonts (no-op if none present)
    register_directory("app/assets/fonts")

    pages_ops = compose(tmpl, root)

    buf = io.BytesIO()
    page_w = tmpl.get("page",{}).get("width", 612)
    page_h = tmpl.get("page",{}).get("height", 792)
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    # Render ops
    for p, ops in enumerate(pages_ops):
        for op in ops:
            if op["op"] == "text":
                draw_text(c, op.get("text",""), op.get("x",0), op.get("y",0),
                          font=op.get("font","Helvetica"), size=op.get("size",10),
                          align=op.get("align","left"), max_width=op.get("max_width"))
            elif op["op"] == "line":
                c.setLineWidth(op.get("width",0.5))
                c.line(op["x1"], op["y1"], op["x2"], op["y2"])
            elif op["op"] == "image":
                try:
                    c.drawImage(op["path"], op["x"], op["y"], width=op.get("width"), height=op.get("height"),
                                preserveAspectRatio=True, mask='auto')
                except Exception:
                    pass
        # QR of XML hash at footer
        h = hashlib.sha256(xml_str.encode("utf-8")).hexdigest()
        img = qrcode.make(h)
        img_buf = io.BytesIO()
        img.save(img_buf, format='PNG')
        img_buf.seek(0)
        c.drawImage(img_buf, page_w - 1.5*inch, 0.6*inch, width=0.75*inch, height=0.75*inch, preserveAspectRatio=True, mask='auto')
        c.showPage()

    c.save()
    return buf.getvalue()
