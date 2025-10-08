# Title Document Creator – Alberta SPIN 2

Production-ready pipeline for generating deterministic Alberta (SPIN 2) land title certificates. The service ingests
fixed-width ASCII exports or prior PDFs, produces canonical XML validated against the official XSD, and renders
pixel-positioned PDF/A-2b output from a JSON template.

## Installation

1. **Clone the repository** (using your desired folder name, e.g. `titan4title`).
   ```bash
   git clone https://github.com/your-org/titan4title.git
   ```
2. **Bootstrap the environment** by running the installation helper from the parent directory or the project root.
   ```bash
   ./install_titan4title.sh
   # or the /runinstall alias
   ```
   This script provisions `.venv/`, installs Python dependencies, and downloads the required domain assets:
   - `app/data/xsd/spin2_title_result.xsd`
   - `app/assets/icc/sRGB.icc`

3. **Activate the virtual environment** when you want to work locally.
   ```bash
   source .venv/bin/activate
   ```

4. **Start the API** (directly or via Docker, depending on your deployment target).
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   # or docker compose up --build
   ```
   FastAPI docs will be available at <http://localhost:8000/docs>.

## Environment & setup

*The installation helper handles these steps automatically; use this section when provisioning manually or in constrained environments.*

1. **Python environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   ReportLab, lxml, xmlschema, PyMuPDF, and Typer are required for the full toolchain.

2. **Domain assets**
   - XSD: place `spin2_title_result.xsd` at `app/data/xsd/spin2_title_result.xsd` (obtain from SPIN 2).
   - ICC profile: add `sRGB.icc` to `app/assets/icc/sRGB.icc` for compliant PDF/A generation.
   - Fonts: drop TTF/OTF files into `app/assets/fonts/` and map aliases in `fontmap.json` (e.g. `BodySerif`, `BodySans`).
   - Crest/seal: replace `app/assets/images/crest.png` with the approved artwork.

3. **Run the API**
   ```bash
   uvicorn app.main:app --reload
   # or docker compose up --build
   ```
   Interactive docs: <http://localhost:8000/docs>

## CLI workflows

```bash
# ASCII → XML using the YAML mapping
python cli.py parse-ascii examples/sample_ascii.txt > out.xml

# Validate canonical XML against the SPIN 2 schema
python cli.py validate out.xml

# Render deterministic PDF (PDF/A by default)
python cli.py render out.xml --template-id alberta_title_v1 --out title.pdf
python cli.py render out.xml --no-pdfa --out draft.pdf
```

The renderer honours aliases defined in `app/assets/fonts/fontmap.json` and embeds the ICC profile when available.

## Pipeline overview

1. **ASCII parsing** (`app/services/ascii_parser.py`)
   - Interpretation driven by `app/data/mappings/alberta_spin2_ascii_v1.yaml` with trimming, numeric/date coercion,
     and record aggregation.
   - Outputs canonical `ProductTitleResult` XML (tests: `tests/test_ascii_parser.py`).

2. **XSD validation** (`app/services/xml_validator.py`)
   - Caches the compiled SPIN 2 schema and returns structured error objects (message, line, column, xpath).

3. **PDF ingest backfill** (`app/services/pdf_ingest.py`)
   - Uses PyMuPDF geometry to detect title numbers, legal descriptions, owners, and instruments.
   - Produces candidate XML plus a confidence score (tests: `tests/test_pdf_ingest.py`).

4. **Template composition** (`app/services/template_engine.py`)
   - Supports `TextBox` wrapping with baseline grid alignment, repeating tables with widow/orphan control, absolute
     positioning for images and rules, and XPath bindings.

5. **Rendering** (`app/services/renderer.py`)
   - Deterministic metadata (`ID`, creation/mod timestamps) and PDF/A-2b via `app/utils/pdfa.py`.
   - QR code derived from the canonical XML SHA-256; disable via template `page.qr.enabled = false`.

## Template & samples

- Primary template: `app/data/templates/alberta_title_v1.json` (v1.1.0) mirrors the Alberta certificate layout using the
  new layout features.
- Canonical sample XML: `app/data/samples/sample.xml` renders to a two-page certificate with multiple instruments.
- Sample manifest: `app/data/samples/manifest.json` records the SHA-256 of reference XML (extend with rendered PDF hashes
  when available to document determinism across environments).

## API surface (highlights)

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/parse-ascii` | Upload ASCII export → canonical XML |
| `POST /v1/validate`   | Schema validation with detailed errors |
| `POST /v1/ingest-pdf` | Extract best-effort XML candidates from prior PDFs |
| `POST /v1/render`     | Render XML to PDF/PDF-A using selected template |
| `POST /v1/reserve-title-number` | Deterministic title number reservation strategies |
| `GET /v1/templates`   | Enumerate templates with page metadata |

Refer to `openapi.yaml` or `/docs` for complete request/response examples.

## Testing

```bash
pytest -q
```

Tests that require ReportLab/PyMuPDF are automatically skipped when the dependencies are absent. Core coverage spans the
ASCII parser, PDF ingest heuristics, template pagination, and renderer determinism (hash-based).

## Font extraction helper

```
python -m app.tools.extract_fonts source.pdf app/assets/fonts/exported/
```

The helper exports embedded font programs (when permitted) and produces a starter `fontmap.json` that can be merged into
`app/assets/fonts/fontmap.json`.

## Determinism & provenance

- Renderer metadata is frozen (creator, producer, timestamps) and the PDF document ID equals the SHA-256 of the canonical XML.
- QR codes encode the same SHA-256, enabling quick verification of distributed copies.
- Extend `app/data/samples/manifest.json` with additional XML/PDF pairs to document reproducibility across environments.

© 2025
