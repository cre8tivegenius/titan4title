"""Extract embedded fonts from a PDF for registration within the service."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict


LOGGER = logging.getLogger(__name__)


def extract_fonts(pdf_path: Path, output_dir: Path) -> Dict[str, Dict[str, str]]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:  # pragma: no cover - tool dependency guard
        raise RuntimeError("PyMuPDF (fitz) is required for font extraction") from exc

    doc = fitz.open(pdf_path)
    fonts: Dict[int, Dict[str, str]] = {}
    for page in doc:
        for font in page.get_fonts(full=True):
            xref = font[0]
            name = font[3]
            fonts.setdefault(xref, {"name": name})

    fontmap: Dict[str, Dict[str, str]] = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    for xref, info in fonts.items():
        name = info["name"].lstrip("/")
        try:
            font_name, extension, font_bytes, _ = doc.extract_font(xref)
        except Exception:
            LOGGER.warning("Unable to extract font %s (xref %s)", name, xref)
            fontmap[name] = {"builtin": name}
            continue

        filename = f"{name.replace(' ', '_')}_{xref}.{extension}"
        out_path = output_dir / filename
        out_path.write_bytes(font_bytes)
        fontmap[name] = {"file": filename}

    return fontmap


def main() -> None:  # pragma: no cover - CLI entry
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Extract embedded fonts from a PDF")
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument("out", type=Path, help="Directory to write extracted fonts")
    args = parser.parse_args()

    fontmap = extract_fonts(args.pdf, args.out)
    map_path = args.out / "fontmap.json"
    map_path.write_text(json.dumps(fontmap, indent=2), encoding="utf-8")
    LOGGER.info("Wrote %s and %d fonts", map_path, len(fontmap))


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
