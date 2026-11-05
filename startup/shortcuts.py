"""Create per-user launch shortcuts after installation succeeds."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys


def desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def desktop_entry(root: Path) -> str:
    command = str(root / "startup" / "launch_linux.sh").replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        command = command.replace(character, "\\" + character)
    quoted_command = f'"{command}"'
    return (
        "[Desktop Entry]\nType=Application\nName=FITS\n"
        "Comment=Fluorescent Image Tracking Software\n"
        f"Exec={desktop_value(quoted_command)}\n"
        f"Path={desktop_value(str(root))}\n"
        f"Icon={desktop_value(str(root / 'assets' / 'fits_icon.png'))}\n"
        "Terminal=false\nStartupNotify=true\nCategories=Science;\n"
        "Keywords=microscopy;fluorescence;tracking;images;\n"
    )


def install_macos_shortcut(root: Path, output_dir: Path | None, refresh_only: bool,
                           report: Callable[[str], None]) -> None:
    """A Terminal launcher keeps install/update progress available on macOS."""
    destination = (output_dir or Path.home() / "Applications") / "FITS.command"
    launcher = root / "startup" / "launch_macos.sh"
    contents = "#!/bin/bash\nexec /bin/bash " + shlex.quote(str(launcher)) + ' "$@"\n'
    if refresh_only and not destination.exists():
        return
    if destination.exists() and destination.read_text(encoding="utf-8") != contents:
        if refresh_only:
            return
        report(f"Existing FITS launcher: {destination}\nNew checkout: {root}")
        try:
            answer = input("Point the FITS launcher to this checkout? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            report("Existing launcher kept. Run bash startup/launch_macos.sh from this checkout.")
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents, encoding="utf-8")
    destination.chmod(0o755)
    report(f"Installed {destination}. Double-click it in Finder to launch FITS.")


def install_shortcut(root: Path, *, output_dir: Path | None = None, refresh_only: bool = False,
                     report: Callable[[str], None] = print) -> None:
    if sys.platform == "win32":
        environment = os.environ.copy()
        environment["FITS_INSTALL_ROOT"] = str(root)
        environment["FITS_REFRESH_SHORTCUTS"] = "1" if refresh_only else "0"
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(root / "startup" / "windows_shortcut.ps1")],
            env=environment, check=True,
        )
        return
    if sys.platform == "darwin":
        install_macos_shortcut(root, output_dir, refresh_only, report)
        return
    if not (root / ".venv" / "bin" / "python").is_file():
        raise RuntimeError("Create the FITS environment before installing a shortcut.")
    if not (root / "assets" / "fits_icon.png").is_file():
        raise RuntimeError("Missing FITS icon.")
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    destination_dir = output_dir or data_home / "applications"
    destination = destination_dir / "fits.desktop"
    if refresh_only and not destination.exists():
        return
    contents = desktop_entry(root)
    if destination.exists():
        old = destination.read_text(encoding="utf-8")
        expected_path = f"Path={desktop_value(str(root))}"
        if expected_path not in old.splitlines():
            if refresh_only:
                return  # Do not repoint another checkout's shortcut during updates.
            old_path = next((line[5:] for line in old.splitlines() if line.startswith("Path=")), "unknown")
            report(f"Existing FITS shortcut: {old_path}\nNew checkout: {root}")
            try:
                answer = input("Point the FITS shortcut to this checkout? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                report("Existing shortcut kept. Open this checkout with startup/launch_linux.sh.")
                return
    destination_dir.mkdir(parents=True, exist_ok=True)
    launcher = root / "startup" / "launch_linux.sh"
    launcher.chmod(launcher.stat().st_mode | 0o100)
    destination.write_text(contents, encoding="utf-8")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(destination_dir)], check=True)
    report(f"Installed {destination}. Search for FITS in Applications.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="Unix only: write the shortcut here for review.")
    arguments = parser.parse_args()
    install_shortcut(Path(__file__).resolve().parents[1], refresh_only=arguments.refresh_existing,
                     output_dir=arguments.output_dir)
