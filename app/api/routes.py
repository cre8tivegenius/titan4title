import glob
import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from lxml import etree
from pydantic import BaseModel, Field

from app.services import ascii_parser, pdf_ingest, renderer, title_numbers, xml_validator

router = APIRouter()

class XMLBody(BaseModel):
    xml: str
    template_id: Optional[str] = "alberta_title_v1"
    options: Dict[str, Any] = Field(default_factory=lambda: {"pdfa": True})

@router.get("/templates")
async def list_templates():
    paths = glob.glob("app/data/templates/*.json")
    items = []
    for p in paths:
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            stat = os.stat(p)
            items.append(
                {
                    "template_id": data.get("template_id", Path(p).stem),
                    "version": data.get("version"),
                    "page": data.get("page", {}),
                    "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat() + "Z",
                }
            )
        except Exception:
            continue
    return {"templates": items}

@router.post("/parse-ascii")
async def parse_ascii(file: Optional[UploadFile] = File(None), ascii_text: Optional[str] = Form(None)):
    if file is None and (ascii_text is None or not ascii_text.strip()):
        raise HTTPException(status_code=400, detail="Provide ASCII content via file upload or ascii_text form field.")

    content = ascii_text or ""
    if file is not None:
        try:
            payload = await file.read()
        except Exception as exc:  # pragma: no cover - upload read guard
            raise HTTPException(status_code=400, detail=f"Unable to read uploaded file: {exc}") from exc
        if not payload:
            raise HTTPException(status_code=400, detail="Uploaded ASCII export is empty.")
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="Uploaded ASCII export must be UTF-8 encoded.") from exc

    try:
        xml = ascii_parser.parse_ascii_to_xml(content, mapping_path="app/data/mappings/alberta_spin2_ascii_v1.yaml")
    except HTTPException:
        raise
    except ascii_parser.MappingLoadError as exc:
        raise HTTPException(status_code=500, detail=f"ASCII mapping unavailable: {exc}") from exc
    except ascii_parser.RecordMatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse ASCII payload: {exc}") from exc

    return {"xml": xml}

@router.post("/validate")
async def validate_xml(body: XMLBody):
    ok, errors = xml_validator.validate(body.xml)
    return {"ok": ok, "errors": errors}

@router.post("/ingest-pdf")
async def ingest_pdf(file: UploadFile = File(...)):
    try:
        data = await file.read()
    except Exception as exc:  # pragma: no cover - upload read guard
        raise HTTPException(status_code=400, detail=f"Unable to read uploaded PDF: {exc}") from exc

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    try:
        xml_candidates, confidence = pdf_ingest.pdf_to_xml_candidates(data)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to ingest PDF: {exc}") from exc

    return {"xml_candidates": xml_candidates, "confidence": confidence}

@router.post("/render")
async def render_pdf(body: XMLBody):
    if body.xml is None or not body.xml.strip():
        raise HTTPException(status_code=400, detail="XML payload is required to generate a PDF.")

    try:
        pdf_bytes = renderer.render(body.xml, template_id=body.template_id, options=body.options or {})
    except HTTPException:
        raise
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"XML not well-formed: {exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to render PDF: {exc}") from exc

    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")

class ReserveBody(BaseModel):
    strategy: Optional[str] = "sequential"
    seed: Optional[str] = None

@router.post("/reserve-title-number")
async def reserve_title_number(body: ReserveBody):
    tn = title_numbers.reserve(strategy=body.strategy, seed=body.seed)
    return {"title_number": tn}
