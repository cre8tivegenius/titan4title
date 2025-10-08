import sys
from pathlib import Path


# Ensure the repository root is importable so that `app` can be resolved when
# running tests with a bare `pytest` invocation.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Provide a lightweight YAML loader fallback for environments where PyYAML is
# not installed (e.g., the execution sandbox for tests). The canonical mapping
# file is valid JSON so the fallback delegates to the standard library.
try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - dependency availability guard
    import json
    import types

    yaml_stub = types.ModuleType("yaml")

    def safe_load(stream):
        content = stream.read() if hasattr(stream, "read") else stream
        return json.loads(content)

    yaml_stub.safe_load = safe_load  # type: ignore[attr-defined]
    sys.modules["yaml"] = yaml_stub

