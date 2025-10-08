from typing import Tuple, List, Dict, Any
from lxml import etree
import os

XSD_PATH = os.environ.get("SPIN2_XSD_PATH", "app/data/xsd/spin2_title_result.xsd")

def validate(xml_str: str) -> Tuple[bool, List[Dict[str, Any]]]:
    errors = []
    try:
        doc = etree.fromstring(xml_str.encode("utf-8"))
    except Exception as e:
        return False, [dict(message=f"XML not well-formed: {e}", line=None, column=None)]
    if os.path.exists(XSD_PATH):
        try:
            with open(XSD_PATH, "rb") as f:
                schema_doc = etree.parse(f)
            schema = etree.XMLSchema(schema_doc)
            schema.assertValid(doc)
            return True, []
        except etree.DocumentInvalid as e:
            for entry in schema.error_log:
                errors.append(dict(message=entry.message, line=entry.line, column=entry.column))
            return False, errors
        except Exception as e:
            return False, [dict(message=f"XSD load error: {e}", line=None, column=None)]
    else:
        return True, []
