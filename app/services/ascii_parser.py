from lxml import etree
import yaml, re
from typing import Dict, Any, List

def _parse_line(line: str, spec: Dict[str, Any]) -> Dict[str, Any] | None:
    match = spec.get("match", {})
    type_at = match.get("type_at", 1) - 1
    equals = match.get("equals", None)
    if equals and not line[type_at:type_at+len(equals)] == equals:
        return None
    out = {}
    for name, field in spec.get("fields", {}).items():
        start = field.get("start", 1) - 1
        ln = field.get("len", 0)
        raw = line[start:start+ln]
        if field.get("trim", True):
            raw = raw.strip()
        if field.get("int"):
            try: out[name] = int(raw)
            except: out[name] = None
        elif "parse" in field and "date" in field["parse"]:
            out[name] = raw  # leave as raw YYYYMMDD for now
        else:
            out[name] = raw
    return out

def parse_ascii_to_xml(ascii_text: str, mapping_path: str) -> str:
    mapping = yaml.safe_load(open(mapping_path, "r"))
    records = mapping.get("records", [])
    root = etree.Element("Title")

    owners_el = etree.SubElement(root, "Owners")
    instruments_el = etree.SubElement(root, "Instruments")

    for line in ascii_text.splitlines():
        for rec in records:
            parsed = _parse_line(line, rec)
            if parsed is None:
                continue
            rid = rec.get("id")
            if rid == "TITLE_HEADER":
                if parsed.get("title_number"):
                    etree.SubElement(root, "TitleNumber").text = parsed["title_number"]
                if parsed.get("linc"):
                    land = root.find("Land") or etree.SubElement(root, "Land")
                    ident = etree.SubElement(land, "Identifier")
                    etree.SubElement(ident, "LINC").text = parsed["linc"]
            elif rid == "OWNER":
                o = etree.SubElement(owners_el, "Owner")
                etree.SubElement(o, "DisplayName").text = parsed.get("name","")
                if parsed.get("type"):
                    etree.SubElement(o, "Type").text = parsed["type"]
            elif rid == "INSTRUMENT":
                i = etree.SubElement(instruments_el, "Instrument")
                if parsed.get("number"): i.set("number", parsed["number"])
                if parsed.get("i_type"): i.set("type", parsed["i_type"])
                if parsed.get("date"): i.set("date", parsed["date"])
                etree.SubElement(i, "Remarks").text = parsed.get("remarks","")
            # add more record mappings as your YAML evolves
            break  # stop scanning rec specs once one matched

    return etree.tostring(root, pretty_print=True, encoding="utf-8").decode("utf-8")
