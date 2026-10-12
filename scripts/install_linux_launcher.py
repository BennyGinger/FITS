"""Install a per-user Ubuntu Applications-menu entry for this checkout."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess


def desktop_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Write the launcher here instead of installing into the user Applications menu.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    launcher = root / "launch.sh"
    icon = root / "assets" / "fits_logo.png"
    if not (root / ".venv" / "bin" / "python").is_file():
        parser.error("Create the FITS virtual environment with uv sync before installing the launcher.")
    if not icon.is_file():
        parser.error(f"Missing launcher icon: {icon}")
    # Exec uses desktop-entry quoting, followed by desktop-string escaping.
    command = str(launcher).replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        command = command.replace(character, "\\" + character)
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    destination_dir = args.output_dir or data_home / "applications"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / "fits.desktop"
    quoted_command = f'"{command}"'
    destination.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=FITS\n"
        "Comment=Fluorescent Image Tracking Software\n"
        f"Exec={desktop_value(quoted_command)}\n"
        f"Path={desktop_value(str(root))}\n"
        f"Icon={desktop_value(str(icon))}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        "Categories=Science;\n"
        "Keywords=microscopy;fluorescence;tracking;images;\n",
        encoding="utf-8",
    )
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(destination_dir)], check=True)
    print(f"Installed {destination}. Search for FITS in Applications.")


if __name__ == "__main__":
    main()
