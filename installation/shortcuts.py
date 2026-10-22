"""Create per-user launch shortcuts after installation succeeds."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import subprocess
import sys


def desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def desktop_entry(root: Path) -> str:
    command = str(root / "launch.sh").replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        command = command.replace(character, "\\" + character)
    quoted_command = f'"{command}"'
    return (
        "[Desktop Entry]\nType=Application\nName=FITS\n"
        "Comment=Fluorescent Image Tracking Software\n"
        f"Exec={desktop_value(quoted_command)}\n"
        f"Path={desktop_value(str(root))}\n"
        f"Icon={desktop_value(str(root / 'assets' / 'fits_logo.png'))}\n"
        "Terminal=false\nStartupNotify=true\nCategories=Science;\n"
        "Keywords=microscopy;fluorescence;tracking;images;\n"
    )


def install_shortcut(root: Path, *, output_dir: Path | None = None,
                     report: Callable[[str], None] = print) -> None:
    if sys.platform == "win32":
        environment = os.environ.copy()
        environment["FITS_INSTALL_ROOT"] = str(root)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(root / "installation" / "windows_shortcut.ps1")],
            env=environment, check=True,
        )
        return
    if not (root / ".venv" / "bin" / "python").is_file():
        raise RuntimeError("Create the FITS environment before installing a shortcut.")
    if not (root / "assets" / "fits_logo.png").is_file():
        raise RuntimeError("Missing FITS logo.")
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    destination_dir = output_dir or data_home / "applications"
    destination = destination_dir / "fits.desktop"
    contents = desktop_entry(root)
    if destination.exists():
        old = destination.read_text(encoding="utf-8")
        expected_path = f"Path={desktop_value(str(root))}"
        if expected_path not in old.splitlines():
            old_path = next((line[5:] for line in old.splitlines() if line.startswith("Path=")), "unknown")
            report(f"Existing FITS shortcut: {old_path}\nNew checkout: {root}")
            try:
                answer = input("Point the FITS shortcut to this checkout? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                report("Existing shortcut kept. Open this checkout with launch.sh.")
                return
    destination_dir.mkdir(parents=True, exist_ok=True)
    launcher = root / "launch.sh"
    launcher.chmod(launcher.stat().st_mode | 0o100)
    destination.write_text(contents, encoding="utf-8")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(destination_dir)], check=True)
    report(f"Installed {destination}. Search for FITS in Applications.")
