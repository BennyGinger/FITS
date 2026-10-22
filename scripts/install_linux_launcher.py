"""Install a per-user Ubuntu Applications-menu entry for this checkout."""

import argparse
from pathlib import Path
import sys

# Compatibility entry point for existing checkout documentation and commands.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "installation"))
from shortcuts import install_shortcut


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="Write the launcher here instead of installing into the user Applications menu.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    install_shortcut(root, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
