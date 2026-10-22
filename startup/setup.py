"""Install this FITS checkout using only the Python standard library."""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from shortcuts import install_shortcut
from state import command_environment, record_bootstrap, record_installation, require_independent_python, show_project_files


ROOT = Path(__file__).resolve().parents[1]


class Installer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.log_path = root / "startup" / "logs" / "install.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def message(self, message: str) -> None:
        if sys.stdout is not None:
            print(message, flush=True)
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write(message + "\n")

    def run(self, *command: str) -> str:
        self.message("Running: " + subprocess.list2cmdline(command))
        environment = command_environment(self.root)
        with subprocess.Popen(
            command, cwd=self.root, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        ) as process:
            assert process.stdout is not None
            output = []
            for line in process.stdout:
                self.message(line.rstrip("\n"))
                output.append(line)
            if process.wait():
                raise RuntimeError(f"Command failed: {subprocess.list2cmdline(command)}")
        return "".join(output)

    def check_checkout(self) -> None:
        if not (self.root / ".git").exists():
            raise RuntimeError("Use a Git clone of FITS, not a downloaded ZIP archive.")
        for program in ("git", "uv"):
            if shutil.which(program) is None:
                raise RuntimeError(f"{program} is required and must be on PATH.")
        with tempfile.TemporaryFile(dir=self.root):
            pass
        # Inspect initialized modules recursively before changing any checkout.
        statuses = self.run("git", "submodule", "status", "--recursive")
        for line in statuses.splitlines():
            if line.startswith(("+", "U")):
                raise RuntimeError(
                    "A submodule differs from FITS's recorded commit or has conflicts. "
                    "Save your module work and reconcile its commit before reinstalling:\n" + line
                )
        dirty = self.run(
            "git", "submodule", "foreach", "--quiet", "--recursive",
            'git status --porcelain --untracked-files=normal',
        )
        if dirty.strip():
            raise RuntimeError(
                "A submodule has local changes. Save and reconcile them before reinstalling. "
                "No submodule checkout was changed."
            )

    def install(self, no_shortcut: bool) -> None:
        self.message(f"\nFITS installation: {datetime.now().isoformat(timespec='seconds')}")
        self.message(f"Checkout: {self.root}")
        self.check_checkout()
        self.run("git", "submodule", "sync", "--recursive")
        self.run("git", "submodule", "update", "--init", "--recursive")
        lock_path = self.root / "uv.lock"
        previous_lock = lock_path.read_bytes() if lock_path.exists() else None
        show_project_files(self.root)
        self.run("uv", "sync", "--python", "3.12")
        if lock_path.read_bytes() != previous_lock:
            self.message("Note: uv sync updated uv.lock; review that change before committing.")
        python = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.run(str(python), str(self.root / "startup" / "verify.py"))
        record_bootstrap(self.root)
        record_installation(self.root)
        if not no_shortcut:
            install_shortcut(self.root, report=self.message)
        self.message("FITS installation complete. No GPU is required to open the GUI.")
        self.message("Models are downloaded on first use; no model weights were requested by this installer.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-shortcut", action="store_true", help="Install without creating a menu shortcut.")
    args = parser.parse_args()
    installer = None
    try:
        if sys.platform not in ("linux", "win32"):
            raise RuntimeError("This installer supports Linux and Windows.")
        installer = Installer(ROOT)
        require_independent_python(ROOT)
        installer.install(args.no_shortcut)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        if installer is None:
            print(f"Installation failed: {error}", file=sys.stderr)
        else:
            installer.message(f"Installation failed: {error}")
            installer.message(f"Log: {installer.log_path}\nFix the reported problem and rerun the installer.")
        return 1
    except KeyboardInterrupt:
        print("\nInstallation interrupted. Rerun the installer to retry.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
