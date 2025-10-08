# Title Document Creator – Pro Scaffold (Alberta SPIN 2)

High-quality scaffold favoring **accuracy and reproducibility** over speed. Implements a template-driven renderer,
deterministic outputs, schema validation, and mapping-based ASCII parsing. Ready for contractors.

## Quick start

```bash
docker compose up --build
open http://localhost:8000/docs
```

## Drop-in assets (already pre-populated if you uploaded them)
- XSD: `app/data/xsd/spin2_title_result.xsd` (✓ copied)
- Golden PDF: `app/data/samples/ARLO/sample.pdf` (✓ copied)

## Key modules
- `app/services/ascii_parser.py` – fixed-width parser using YAML mapping
- `app/services/xml_validator.py` – XSD validation (lxml+xmlschema)
- `app/services/template_engine.py` – XPath bindings + layout composition
- `app/services/renderer.py` – absolute-position renderer with pagination
- `app/services/pdf_ingest.py` – prior PDF heuristics (stub but structured)
- `app/services/font_registry.py` – dynamic TTF registration
- `app/tools/` – hooks for font extraction (to be wired if needed)

**PDF/A-2b** is supported *if* you place an ICC profile at `app/assets/icc/sRGB.icc`. Otherwise standard PDF is emitted.

© 2025
