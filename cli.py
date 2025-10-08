import typer, json, sys
from app.services import ascii_parser, xml_validator, renderer

app = typer.Typer()

@app.command()
def parse_ascii(infile: str, mapping: str = "app/data/mappings/alberta_spin2_ascii_v1.yaml"):
    text = open(infile, "r", encoding="utf-8").read()
    xml = ascii_parser.parse_ascii_to_xml(text, mapping)
    print(xml)

@app.command()
def validate(xmlfile: str):
    xml = open(xmlfile, "r", encoding="utf-8").read()
    ok, errors = xml_validator.validate(xml)
    print(json.dumps({"ok": ok, "errors": errors}, indent=2))

@app.command()
def render(xmlfile: str, template_id: str = "alberta_title_v1", out: str = "out.pdf"):
    xml = open(xmlfile, "r", encoding="utf-8").read()
    pdf = renderer.render(xml, template_id=template_id)
    open(out, "wb").write(pdf)
    print(out)

if __name__ == "__main__":
    app()
