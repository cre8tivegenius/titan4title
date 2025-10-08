"""Schema-backed XML validation utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from lxml import etree
import os
from pathlib import Path
import threading
from io import BytesIO
from xmlschema import XMLSchema, XMLSchemaException


__all__ = ["validate", "reset_schema_cache"]


DEFAULT_XSD_PATH = Path("app/data/xsd/spin2_title_result.xsd")
XSD_ENV_VARIABLE = "SPIN2_XSD_PATH"

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_CACHE: Optional[XMLSchema] = None
_SCHEMA_PATH_CACHE: Optional[Path] = None


@dataclass(slots=True)
class ValidationIssue:
    """Structured information about a validation problem."""

    message: str
    line: Optional[int]
    column: Optional[int]
    xpath: Optional[str]

    def asdict(self) -> Dict[str, Optional[int | str]]:
        return {
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "xpath": self.xpath,
        }


def _resolve_schema_path() -> Path:
    env_path = os.getenv(XSD_ENV_VARIABLE)
    if env_path:
        candidate = Path(env_path)
    else:
        candidate = DEFAULT_XSD_PATH
    return candidate


def _load_schema() -> XMLSchema:
    global _SCHEMA_CACHE, _SCHEMA_PATH_CACHE
    schema_path = _resolve_schema_path().resolve()
    with _SCHEMA_LOCK:
        if _SCHEMA_CACHE is not None and _SCHEMA_PATH_CACHE == schema_path:
            return _SCHEMA_CACHE

        if not schema_path.exists():
            raise FileNotFoundError(
                f"SPIN 2 XSD not found at '{schema_path}'. Set {XSD_ENV_VARIABLE} or place the XSD in the default location."
            )

        with schema_path.open("rb") as fh:
            # Some official distributions include trailing NULs; strip them defensively.
            data = fh.read().rstrip(b"\x00")

        try:
            schema = XMLSchema(BytesIO(data), base_url=str(schema_path))
        except XMLSchemaException as exc:  # pragma: no cover - guarded for corrupted distribution
            raise XMLSchemaException(f"Failed to parse XSD at '{schema_path}': {exc}") from exc

        _SCHEMA_CACHE = schema
        _SCHEMA_PATH_CACHE = schema_path
        return schema


def reset_schema_cache() -> None:
    """Clear the in-memory schema cache (primarily for tests)."""

    global _SCHEMA_CACHE, _SCHEMA_PATH_CACHE
    with _SCHEMA_LOCK:
        _SCHEMA_CACHE = None
        _SCHEMA_PATH_CACHE = None


def _iter_issues(schema: XMLSchema, document: etree._Element) -> Iterable[ValidationIssue]:
    for error in schema.iter_errors(document):
        position = getattr(error, "position", None)
        line: Optional[int] = None
        column: Optional[int] = None
        if position and isinstance(position, tuple):
            if len(position) >= 1:
                line = position[0]
            if len(position) >= 2:
                column = position[1]

        message = (error.reason or error.message or str(error)).strip()
        xpath = getattr(error, "path", None)
        yield ValidationIssue(message=message, line=line, column=column, xpath=xpath)


def validate(xml_str: str) -> Tuple[bool, List[Dict[str, Optional[int | str]]]]:
    """Validate an XML string against the SPIN 2 schema.

    Returns a tuple of (ok, issues[]) where each issue exposes message, line, column, and xpath
    when available. The schema is cached after the first successful load for efficiency.
    """

    if xml_str is None or not xml_str.strip():
        issue = ValidationIssue(
            message="XML payload is empty.",
            line=None,
            column=None,
            xpath=None,
        )
        return False, [issue.asdict()]

    try:
        parser = etree.XMLParser(remove_blank_text=False)
        document = etree.fromstring(xml_str.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        line, column = (exc.position if exc.position else (None, None))
        issue = ValidationIssue(
            message=f"XML not well-formed: {exc.msg}",
            line=line,
            column=column,
            xpath=None,
        )
        return False, [issue.asdict()]

    try:
        schema = _load_schema()
    except FileNotFoundError as exc:
        issue = ValidationIssue(message=str(exc), line=None, column=None, xpath=None)
        return False, [issue.asdict()]
    except XMLSchemaException as exc:  # pragma: no cover - defensive
        issue = ValidationIssue(message=str(exc), line=None, column=None, xpath=None)
        return False, [issue.asdict()]

    issues = [issue.asdict() for issue in _iter_issues(schema, document)]
    if issues:
        return False, issues

    return True, []
