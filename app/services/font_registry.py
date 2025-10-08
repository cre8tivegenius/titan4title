"""Font registration utilities with alias support."""

from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path
from typing import Dict


LOGGER = logging.getLogger(__name__)


def _register_font(font_name: str, font_path: str) -> None:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:  # pragma: no cover - dependency guard
        raise RuntimeError("ReportLab is required to register fonts")

    if font_name in pdfmetrics.getRegisteredFontNames():
        return
    try:
        pdfmetrics.registerFont(TTFont(font_name, font_path))
    except Exception as exc:  # pragma: no cover - defensive path for invalid fonts
        LOGGER.warning("Unable to register font '%s' from %s: %s", font_name, font_path, exc)


def register_directory(dir_path: str = "app/assets/fonts", map_path: str | None = None) -> Dict[str, str]:
    """Register fonts within a directory and return alias mappings.

    The optional ``fontmap.json`` allows alias definitions, e.g.

    ```json
    {
      "BodySerif": {"file": "CrimsonText-Regular.ttf"},
      "BodySerifBold": {"file": "CrimsonText-Bold.ttf"},
      "BodySans": {"builtin": "Helvetica"}
    }
    ```
    """

    alias_map: Dict[str, str] = {}
    font_dir = Path(dir_path)
    if not font_dir.is_dir():
        return alias_map

    font_files = sorted(
        glob.glob(str(font_dir / "*.ttf")) + glob.glob(str(font_dir / "*.otf"))
    )
    for path in font_files:
        name = Path(path).stem
        _register_font(name, path)
        alias_map.setdefault(name, name)

    if map_path is None:
        map_path = str(font_dir / "fontmap.json")

    map_file = Path(map_path)
    if map_file.exists():
        try:
            mapping = json.loads(map_file.read_text(encoding="utf-8"))
            for alias in sorted(mapping.keys()):
                entry = mapping[alias] or {}
                if "file" in entry:
                    font_file = font_dir / entry["file"]
                    if not font_file.exists():
                        LOGGER.warning("Font file for alias '%s' not found: %s", alias, font_file)
                        continue
                    font_name = entry.get("font_name", alias)
                    _register_font(font_name, str(font_file))
                    alias_map[alias] = font_name
                elif "builtin" in entry:
                    alias_map[alias] = entry["builtin"]
                else:
                    LOGGER.warning("Alias '%s' missing 'file' or 'builtin' definition", alias)
        except Exception as exc:
            LOGGER.warning("Failed to load font map %s: %s", map_file, exc)

    return alias_map
