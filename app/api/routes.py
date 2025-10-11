import glob
import io
import json
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from lxml import etree
from pydantic import BaseModel, Field, condecimal

from app.services import ascii_parser, pdf_ingest, renderer, title_numbers, title_request_builder, xml_validator

router = APIRouter()

class XMLBody(BaseModel):
    xml: str
    template_id: Optional[str] = "alberta_title_v1"
    options: Dict[str, Any] = Field(default_factory=lambda: {"pdfa": True})


class OwnerParty(BaseModel):
    name: str
    type: Optional[str] = "Individual"
    aliases: Optional[List[str]] = None
    occupation: Optional[str] = None
    address_lines: Optional[List[str]] = None
    province: Optional[str] = None
    postal_code: Optional[str] = None
    role: Optional[str] = None


class OwnerGroup(BaseModel):
    tenancy_type: Optional[str] = None
    interest: Optional[str] = None
    parties: List[OwnerParty]


class NewTitleRequest(BaseModel):
    reference_number: str
    buyer_name: str
    purchase_price: condecimal(gt=0, max_digits=13, decimal_places=2)
    purchase_date: date
    legal_description: str
    municipality: str
    municipality_code: Optional[str] = None
    linc_number: Optional[str] = None
    title_number: Optional[str] = None
    registration_number: Optional[str] = None
    rights_type: Optional[str] = title_request_builder.DEFAULT_RIGHTS_TYPE
    estate: Optional[str] = title_request_builder.DEFAULT_ESTATE
    tenancy_type: Optional[str] = title_request_builder.DEFAULT_TENANCY_TYPE
    template_id: Optional[str] = title_request_builder.DEFAULT_TEMPLATE_ID
    render_options: Dict[str, Any] = Field(default_factory=lambda: {"pdfa": True})
    owner_groups: Optional[List[OwnerGroup]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "reference_number": "REQ-2025-0001",
                "buyer_name": "Andre Yves Lacroix",
                "purchase_price": "650000.00",
                "purchase_date": "2025-10-08",
                "legal_description": "PLAN 0723943 BLOCK 86 LOT 31 EXCEPTING THEREOUT ALL MINES AND MINERALS",
                "municipality": "CITY OF EDMONTON",
            }
        }

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


@router.post("/new-title-request")
async def create_new_title_request(body: NewTitleRequest):
    try:
        owner_groups = [group.model_dump() for group in body.owner_groups] if body.owner_groups else None
        build_result = title_request_builder.build_new_title_xml(
            reference_number=body.reference_number,
            buyer_name=body.buyer_name,
            purchase_price=Decimal(body.purchase_price),
            purchase_date=body.purchase_date,
            legal_description=body.legal_description,
            municipality_name=body.municipality,
            municipality_code=body.municipality_code,
            title_number=body.title_number,
            registration_number=body.registration_number,
            linc_number=body.linc_number,
            rights_type=body.rights_type or title_request_builder.DEFAULT_RIGHTS_TYPE,
            estate=body.estate or title_request_builder.DEFAULT_ESTATE,
            tenancy_type=body.tenancy_type or title_request_builder.DEFAULT_TENANCY_TYPE,
            owner_groups=owner_groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    valid, validation_errors = xml_validator.validate(build_result.xml)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Generated XML failed SPIN2 validation.",
                "errors": validation_errors,
            },
        )

    template_id = body.template_id or title_request_builder.DEFAULT_TEMPLATE_ID
    options = body.render_options or {}
    if "pdfa" not in options:
        options = {**options, "pdfa": True}

    try:
        pdf_bytes = renderer.render(build_result.xml, template_id=template_id, options=options)
    except HTTPException:
        raise
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status_code=500, detail=f"Generated XML not well-formed: {exc}") from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to render generated PDF: {exc}") from exc

    buffer = io.BytesIO(pdf_bytes)
    response = StreamingResponse(buffer, media_type="application/pdf")
    filename = f"title_{build_result.title_number}.pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["X-Title-Number"] = build_result.title_number
    response.headers["X-Registration-Number"] = build_result.registration_number
    response.headers["X-LINC-Number"] = build_result.linc_number
    return response

class ReserveBody(BaseModel):
    strategy: Optional[str] = "sequential"
    seed: Optional[str] = None

@router.post("/reserve-title-number")
async def reserve_title_number(body: ReserveBody):
    tn = title_numbers.reserve(strategy=body.strategy, seed=body.seed)
    return {"title_number": tn}
