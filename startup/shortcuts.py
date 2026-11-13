"""Create per-user launch shortcuts after installation succeeds."""

from __future__ import annotations

from ast import literal_eval
from collections.abc import Callable
from hashlib import sha256
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys


def desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def desktop_entry(root: Path, *, icon_path: Path | None = None) -> str:
    command = str(root / "startup" / "launch_linux.sh").replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        command = command.replace(character, "\\" + character)
    quoted_command = f'"{command}"'
    return (
        "[Desktop Entry]\nType=Application\nName=FIScH\n"
        "Comment=Fluorescent Imaging and Single-cell Histories\n"
        f"Exec={desktop_value(quoted_command)}\n"
        f"Path={desktop_value(str(root))}\n"
        f"Icon={desktop_value(str(icon_path or root / 'assets' / 'fisch_icon.png'))}\n"
        "Terminal=false\nStartupNotify=true\nCategories=Science;\n"
        "Keywords=microscopy;fluorescence;tracking;images;\n"
    )


def _migrate_gnome_favorite(old_id: str, new_id: str, report: Callable[[str], None]) -> bool:
    """
    Move the owned shortcut's dock pin and report whether the old shortcut can be removed.
    """
    if "gnome" not in os.environ.get("XDG_CURRENT_DESKTOP", "").casefold().split(":"):
        return True
    setting = ["org.gnome.shell", "favorite-apps"]
    read = ["gsettings", "get", *setting]
    try:
        current = subprocess.check_output(read, text=True, stderr=subprocess.PIPE, timeout=5)
        favorites = literal_eval(current.strip().removeprefix("@as "))
        if not isinstance(favorites, list) or not all(isinstance(item, str) for item in favorites):
            raise ValueError("Invalid GNOME favorites list")
        if old_id not in favorites:
            return True
        if new_id in favorites:
            updated = [item for item in favorites if item != old_id]
        else:
            updated = [new_id if item == old_id else item for item in favorites]
        subprocess.run(["gsettings", "set", *setting, repr(updated)], check=True,
                       capture_output=True, timeout=5)
        saved = subprocess.check_output(read, text=True, stderr=subprocess.PIPE, timeout=5)
        if literal_eval(saved.strip().removeprefix("@as ")) != updated:
            raise ValueError("GNOME did not save the updated dock pin")
    except (OSError, subprocess.SubprocessError, SyntaxError, ValueError):
        report("Could not update the GNOME dock pin. Rerun the installer to retry.")
        return False
    report("Updated the GNOME dock pin to FIScH.")
    return True


def install_macos_shortcut(root: Path, output_dir: Path | None, refresh_only: bool,
                           report: Callable[[str], None]) -> None:
    """A Terminal launcher keeps install/update progress available on macOS."""
    destination = (output_dir or Path.home() / "Applications") / "FIScH.command"
    launcher = root / "startup" / "launch_macos.sh"
    contents = "#!/bin/bash\nexec /bin/bash " + shlex.quote(str(launcher)) + ' "$@"\n'
    legacy = destination.with_name("FITS.command")
    owns_legacy = legacy.is_file() and legacy.read_text(encoding="utf-8") == contents
    if refresh_only and not destination.exists() and not owns_legacy:
        return
    if destination.exists() and destination.read_text(encoding="utf-8") != contents:
        if refresh_only:
            return
        report(f"Existing FIScH launcher: {destination}\nNew checkout: {root}")
        try:
            answer = input("Point the FIScH launcher to this checkout? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            report("Existing launcher kept. Run bash startup/launch_macos.sh from this checkout.")
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(contents, encoding="utf-8")
    destination.chmod(0o755)
    if owns_legacy:
        legacy.unlink(missing_ok=True)
    report(f"Installed {destination}. Double-click it in Finder to launch FIScH.")


def install_shortcut(root: Path, *, output_dir: Path | None = None, refresh_only: bool = False,
                     report: Callable[[str], None] = print) -> None:
    if sys.platform == "win32":
        environment = os.environ.copy()
        environment["FISCH_INSTALL_ROOT"] = str(root)
        environment["FISCH_REFRESH_SHORTCUTS"] = "1" if refresh_only else "0"
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(root / "startup" / "windows_shortcut.ps1")],
            env=environment, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,)
        return
    if sys.platform == "darwin":
        install_macos_shortcut(root, output_dir, refresh_only, report)
        return
    if not (root / ".venv" / "bin" / "python").is_file():
        raise RuntimeError("Create the FIScH environment before installing a shortcut.")
    if not (root / "assets" / "fisch_icon.png").is_file():
        raise RuntimeError("Missing FIScH icon.")
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    destination_dir = output_dir or data_home / "applications"
    destination = destination_dir / "fisch.desktop"
    legacy = destination.with_name("fits.desktop")
    expected_path = f"Path={desktop_value(str(root))}"
    legacy_lines = legacy.read_text(encoding="utf-8").splitlines() if legacy.is_file() else []
    owns_legacy = "Name=FITS" in legacy_lines and expected_path in legacy_lines
    if refresh_only and not destination.exists() and not owns_legacy:
        return
    icon_source = root / "assets" / "fisch_icon.png"
    icon_bytes = icon_source.read_bytes()
    # GNOME can retain an old icon when a different image reuses the same path.
    icon_dir = output_dir / "icons" if output_dir is not None else data_home / "icons"
    icon_path = icon_dir / f"fisch-{sha256(icon_bytes).hexdigest()[:16]}.png"
    contents = desktop_entry(root, icon_path=icon_path)
    if destination.exists():
        old = destination.read_text(encoding="utf-8")
        if expected_path not in old.splitlines():
            if refresh_only:
                return  # Do not repoint another checkout's shortcut during updates.
            old_path = next((line[5:] for line in old.splitlines() if line.startswith("Path=")), "unknown")
            report(f"Existing FIScH shortcut: {old_path}\nNew checkout: {root}")
            try:
                answer = input("Point the FIScH shortcut to this checkout? [y/N] ")
            except EOFError:
                answer = ""
            if answer.strip().lower() not in ("y", "yes"):
                report("Existing shortcut kept. Open this checkout with startup/launch_linux.sh.")
                return
    destination_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)
    if not icon_path.is_file() or icon_path.read_bytes() != icon_bytes:
        icon_path.write_bytes(icon_bytes)
    launcher = root / "startup" / "launch_linux.sh"
    launcher.chmod(launcher.stat().st_mode | 0o100)
    destination.write_text(contents, encoding="utf-8")
    if owns_legacy and (output_dir is not None or _migrate_gnome_favorite(legacy.name, destination.name, report)):
        legacy.unlink(missing_ok=True)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(destination_dir)], check=True)
    report(f"Installed {destination}. Search for FIScH in Applications.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="Unix only: write the shortcut here for review.")
    arguments = parser.parse_args()
    install_shortcut(Path(__file__).resolve().parents[1], refresh_only=arguments.refresh_existing,
                     output_dir=arguments.output_dir)
