from pathlib import Path
from typing import Any
import tomllib


def load_settings(path: str | Path) -> dict[str, Any]:
    input_path = Path(path).expanduser().resolve()
    return tomllib.loads(input_path.read_text())