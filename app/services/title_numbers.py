import uuid
_counter = 1000000

def reserve(strategy: str = "sequential", seed: str | None = None) -> str:
    global _counter
    if strategy == "uuid":
        return str(uuid.uuid4()).upper()
    elif strategy == "external":
        return seed or "PENDING-EXT"
    else:
        _counter += 1
        return f"{_counter}"
