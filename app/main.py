from pathlib import Path
import os

from fastapi import FastAPI

from app.api.routes import router as api_router


APP_DIR = Path(__file__).resolve().parent


def _collect_missing_assets() -> list[str]:
    xsd_env = os.getenv("SPIN2_XSD_PATH")
    xsd_path = Path(xsd_env).expanduser() if xsd_env else APP_DIR / "data" / "xsd" / "spin2_title_result.xsd"
    icc_path = APP_DIR / "assets" / "icc" / "sRGB.icc"

    missing = []
    if not xsd_path.exists():
        missing.append(f"SPIN 2 XSD schema ({xsd_path})")
    if not icc_path.exists():
        missing.append(f"sRGB ICC profile ({icc_path})")
    return missing


app = FastAPI(title="Title Document Creator API (Pro)", version="1.0.0")


@app.on_event("startup")
async def _ensure_domain_assets() -> None:
    missing = _collect_missing_assets()
    if missing:
        asset_list = ", ".join(missing)
        raise RuntimeError(
            "Required domain assets are missing: "
            f"{asset_list}. Run `./install_titan4title.sh` to provision them or update the environment configuration."
        )


app.include_router(api_router, prefix="/v1")
