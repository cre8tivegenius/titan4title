import json
from pathlib import Path
from typing import Optional

import typer

from app.services import ascii_parser, renderer, xml_validator

app = typer.Typer()

@app.command()
def parse_ascii(
    infile: Path,
    mapping: Path = Path("app/data/mappings/alberta_spin2_ascii_v1.yaml"),
):
    text = infile.read_text(encoding="utf-8")
    xml = ascii_parser.parse_ascii_to_xml(text, str(mapping))
    typer.echo(xml)

@app.command()
def validate(xmlfile: Path):
    xml = xmlfile.read_text(encoding="utf-8")
    ok, errors = xml_validator.validate(xml)
    typer.echo(json.dumps({"ok": ok, "errors": errors}, indent=2))

@app.command()
def render(
    xmlfile: Path,
    template_id: str = "alberta_title_v1",
    out: Path = Path("out.pdf"),
    pdfa: bool = typer.Option(True, "--pdfa/--no-pdfa", help="Toggle PDF/A-2b compliance"),
    icc_path: Optional[Path] = typer.Option(None, help="Override ICC profile path"),
):
    xml = xmlfile.read_text(encoding="utf-8")
    options: dict = {"pdfa": pdfa}
    if icc_path:
        options["icc_path"] = str(icc_path)
    pdf_bytes = renderer.render(xml, template_id=template_id, options=options)
    out.write_bytes(pdf_bytes)
    typer.echo(f"wrote {out}")

if __name__ == "__main__":
    app()
