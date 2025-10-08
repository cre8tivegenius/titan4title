#!/usr/bin/env bash

set -euo pipefail

REPO_NAME="titan4title"

if [ ! -f "requirements.txt" ] || [ ! -d "app" ]; then
    if [ -d "$REPO_NAME" ]; then
        echo "Switching into $REPO_NAME/"
        cd "$REPO_NAME"
    else
        echo "Error: run this script from the repository root or its parent directory containing $REPO_NAME/." >&2
        exit 1
    fi
fi

if [ ! -f "requirements.txt" ] || [ ! -d "app" ]; then
    echo "Error: unable to locate project files. Ensure requirements.txt and the app/ directory are present." >&2
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_BIN=python
    else
        echo "Error: Python 3.9+ is required but neither python3 nor python was found on PATH." >&2
        exit 1
    fi
fi

echo "Creating virtual environment in .venv/"
"$PYTHON_BIN" -m venv .venv

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
elif [ -f ".venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/Scripts/activate
else
    echo "Error: virtual environment activation script not found." >&2
    exit 1
fi

echo "Upgrading pip and installing dependencies"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "Ensuring asset directories exist"
mkdir -p app/data/xsd app/assets/icc

download_file() {
    local url=$1
    local destination=$2
    local tmp

    tmp=$(mktemp)

    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$url" -o "$tmp"; then
            rm -f "$tmp"
            echo "Error: failed to download $url" >&2
            exit 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -qO "$tmp" "$url"; then
            rm -f "$tmp"
            echo "Error: failed to download $url" >&2
            exit 1
        fi
    else
        rm -f "$tmp"
        echo "Error: install curl or wget to download required assets." >&2
        exit 1
    fi

    mv "$tmp" "$destination"
}

echo "Downloading SPIN 2 XSD schema"
download_file "https://alta.registries.gov.ab.ca/SpinII/News/Download.aspx?id=0da88839-8424-45f5-b7c7-c9e9b61ea38a" "app/data/xsd/spin2_title_result.xsd"

echo "Downloading sRGB ICC profile"
download_file "https://raw.githubusercontent.com/saucecontrol/Compact-ICC-Profiles/master/profiles/sRGB-v4.icc" "app/assets/icc/sRGB.icc"

cat <<'EOF'

Installation complete.

Next steps:
  source .venv/bin/activate
  uvicorn app.main:app --host 0.0.0.0 --port 8000

Docker users can alternatively run:
  docker compose up --build

Interactive API docs will be available at http://localhost:8000/docs

EOF
