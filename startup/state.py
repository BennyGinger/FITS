"""Local installation receipts; these are ignored by Git."""

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import stat
from tempfile import NamedTemporaryFile


def require_independent_python(root: Path) -> None:
    if Path(sys.executable).absolute().is_relative_to(root / ".venv"):
        raise RuntimeError("Use the OS launcher or installer: the updater must run outside FITS's .venv.")


def show_project_files(root: Path) -> None:
    """Undo legacy Windows hiding of config files, retaining all other attributes."""
    if os.name != "nt":
        return
    for name in ("pyproject.toml", "uv.lock"):
        path = root / name
        try:
            if path.exists() and path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN:
                subprocess.run(["attrib.exe", "-H", str(path)], check=True, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            logging.getLogger(__name__).warning("Could not clear hidden attribute on %s", path)


def command_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    return environment


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8", delete=False) as file:
            temporary = Path(file.name)
            json.dump(value, file)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def dependency_signature(root: Path) -> str:
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "uv.lock", ".gitmodules"):
        path = root / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b"missing")
    # A changed top-level gitlink also changes the complete pinned module tree.
    tree = subprocess.run(
        ["git", "ls-tree", "-rz", "HEAD"], cwd=root, check=True,
        capture_output=True, env=command_environment(root),
    ).stdout
    for entry in tree.split(b"\0"):
        if entry.startswith(b"160000 "):
            digest.update(entry)
    return digest.hexdigest()


def record_installation(root: Path) -> None:
    write_json(root / "startup/logs/installed.json", {
        "dependencies": dependency_signature(root), "modules": module_heads(root),
    })


def module_heads(root: Path, *, recorded: bool = False) -> dict[str, str]:
    value = '"$sha1"' if recorded else '"$(git rev-parse HEAD)"'
    command = 'printf "%s\\0%s\\0" "$displaypath" ' + value
    result = subprocess.run(
        ["git", "submodule", "foreach", "--quiet", "--recursive", command],
        cwd=root, env=command_environment(root), check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    fields = result.stdout.split("\0")
    return dict(zip(fields[:-1:2], fields[1::2], strict=True))


def needs_repair(root: Path) -> bool:
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file() or (root / "startup/logs/update-pending.json").exists():
        return True
    receipt = root / "startup/logs/installed.json"
    if not receipt.exists():
        return False  # Existing installations predating the updater remain usable.
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        return saved["dependencies"] != dependency_signature(root)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return True


def record_bootstrap(root: Path) -> Path:
    result = subprocess.run(
        ["uv", "python", "find", "--system", "--managed-python", "3.12"], cwd=root,
        env=command_environment(root), check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    python = Path(result.stdout.strip())
    if not python.is_absolute() or not python.is_file() or python.is_relative_to(root / ".venv"):
        raise RuntimeError("Could not locate uv's independent managed Python 3.12.")
    path = root / "startup/logs/bootstrap-python.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-16 is read directly by Windows Script Host, including non-ASCII paths.
    path.write_text(str(python), encoding="utf-16" if os.name == "nt" else "utf-8")
    return python
