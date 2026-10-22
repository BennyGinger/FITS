"""Independent startup check, update/repair handoff, and FITS process supervisor."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from tempfile import TemporaryDirectory

from locking import BusyError, Lease
from state import command_environment, needs_repair, require_independent_python
from updater import Updater


ROOT = Path(__file__).resolve().parents[1]


def application_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def native_choice(request: dict) -> str:
    """Fallback for a missing/broken Qt installation, using OS tools only."""
    kind = request["kind"]
    accept = "update" if kind == "update" else "repair" if kind == "repair" else "cancel"
    decline = "current" if kind == "update" else "cancel"
    title, message = request.get("title", "FITS"), request["message"]
    if request.get("blocked"):
        accept = decline
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        box = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
        box.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
        box.restype = ctypes.c_int
        if kind == "message" or request.get("blocked"):
            box(None, message, title, 0x40)
            return decline
        explanation = "\n\nYes: update FITS. No: use current version." if kind == "update" else "\n\nRepair this installation now?"
        return accept if box(None, message + explanation, title, 0x124) == 6 else decline
    zenity = shutil.which("zenity")
    if zenity:
        if kind == "message" or request.get("blocked"):
            subprocess.run([zenity, "--info", "--no-markup", "--title", title, "--text", message])
            return decline
        label = "Update FITS" if kind == "update" else "Repair and launch"
        cancel = "Use current version" if kind == "update" else "Close"
        result = subprocess.run([
            zenity, "--question", "--no-markup", "--title", title, "--text", message,
            "--ok-label", label, "--cancel-label", cancel,
        ])
        return accept if result.returncode == 0 else decline
    if sys.stdin and sys.stdin.isatty():
        print(message)
        if kind != "message" and not request.get("blocked"):
            return accept if input(f"{accept.capitalize()} FITS now? [y/N] ").strip().lower() in ("y", "yes") else decline
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", title, message])
    return decline


def ask(updater: Updater, request: dict) -> str:
    python = application_python(updater.root)
    if python.is_file():
        try:
            with TemporaryDirectory(prefix="dialog-", dir=updater.log_path.parent) as directory:
                request_path = Path(directory) / "request.json"
                response_path = Path(directory) / "response.json"
                request_path.write_text(json.dumps(request), encoding="utf-8")
                result = subprocess.run(
                    [str(python), str(updater.root / "startup/update_dialog.py"),
                     str(request_path), str(response_path)],
                    cwd=updater.root, env=command_environment(updater.root),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode == 0:
                    action = json.loads(response_path.read_text(encoding="utf-8"))["action"]
                    if action in ("current", "update", "repair", "cancel"):
                        return action
                updater.message("Qt startup dialog unavailable: " + result.stderr[-2000:])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            updater.message(f"Qt startup dialog unavailable: {error}")
    return native_choice(request)


def run_progress(updater: Updater, *, repair: bool) -> bool:
    """No Qt process is left holding .venv open during synchronization."""
    token = uuid.uuid4().hex
    command = [sys.executable, str(updater.root / "startup/updater.py"), "--root", str(updater.root),
               "--result-token", token]
    if repair:
        command.append("--repair")
    environment = command_environment(updater.root)
    flags = 0
    if os.name == "nt":
        # pythonw has no console; explicitly use its managed python.exe sibling.
        command[0] = str(Path(sys.executable).with_name("python.exe"))
        environment["FITS_UPDATE_CONSOLE"] = "1"
        flags = subprocess.CREATE_NEW_CONSOLE
    elif sys.stdin and sys.stdin.isatty():
        pass
    elif shutil.which("gnome-terminal"):
        command = ["gnome-terminal", "--wait", "--", *command]
    elif shutil.which("konsole"):
        command = ["konsole", "--nofork", "-e", *command]
    elif shutil.which("xterm"):
        command = ["xterm", "-e", *command]
    else:
        ask(updater, {"kind": "message", "title": "FITS needs a terminal",
                      "message": "Open startup/launch_linux.sh in a terminal to update or repair FITS.\n"
                                 "Your installation has not been changed."})
        return False
    result = subprocess.run(command, cwd=updater.root, env=environment, creationflags=flags)
    try:
        receipt = json.loads((updater.log_path.parent / "update-result.json").read_text(encoding="utf-8"))
        ready = receipt.get("token") == token and receipt.get("ready") is True
    except (OSError, ValueError):
        ready = False
    # Terminal emulators do not all propagate their child's status reliably.
    # Require this specific worker's verification receipt before opening FITS.
    if result.returncode or not ready or needs_repair(updater.root):
        updater.message("Update/repair did not report verified completion; the GUI was not started.")
        return False
    return True


def launch_gui(updater: Updater, arguments: list[str]) -> int:
    environment = command_environment(updater.root)
    environment["FITS_APPLICATION_LOCK"] = str(updater.root / "startup/logs/application.lock")
    with (updater.log_path.parent / "launcher.log").open("a", encoding="utf-8") as log:
        result = subprocess.run(
            [str(application_python(updater.root)), "-m", "fits.gui.main", *arguments],
            cwd=updater.root, env=environment, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    return result.returncode


def startup(updater: Updater, arguments: list[str], *, skip_check: bool = False, repair: bool = False) -> int:
    # The supervisor lease lasts through GUI exit. The application lease is also
    # used by direct `uv run fits-gui` instances, and by the update worker.
    with Lease(updater.root / "startup/logs/application.lock"):
        incomplete = needs_repair(updater.root)
        update = None
        if not skip_check and not updater.pending.exists():
            try:
                update = updater.check()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                updater.message(f"Update check unavailable; keeping the current version: {error}")
        if update is not None and not incomplete and not repair:
            message = (f"A newer FITS version is available.\n\n"
                       f"Installed: {update.before[:8]}\nAvailable: {update.target[:8]}\n\n{update.summary}")
            if update.blocked:
                message += "\n\n" + update.blocked
            action = ask(updater, {"kind": "update", "title": "FITS update available",
                                   "message": message, "blocked": bool(update.blocked)})
            if action == "update" and not update.blocked:
                updater.prepare(update)
                repair = True
        elif incomplete or repair:
            action = ask(updater, {"kind": "repair", "title": "FITS installation needs repair",
                                   "message": "This installation needs synchronization before FITS can open.\n"
                                              "Repair it now? An interrupted update will resume its selected version."})
            if action != "repair":
                return 0
            repair = True
    if repair and not run_progress(updater, repair=True):
        return 1
    result = launch_gui(updater, arguments)
    if result:
        updater.message(f"FITS exited with code {result}. Details: {updater.log_path.parent / 'launcher.log'}")
        action = ask(updater, {"kind": "repair", "title": "FITS did not exit normally",
                               "message": "FITS reported an error. Details are in startup/logs/launcher.log.\n"
                                          "You can repair the installation and try again, or close."})
        if action == "repair" and run_progress(updater, repair=True):
            return launch_gui(updater, arguments)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-update-check", action="store_true", help="Launch the current version without a network check.")
    parser.add_argument("--repair", action="store_true", help="Offer repair of the current installation.")
    parser.add_argument("--check-only", action="store_true", help="Report available FITS updates as JSON without launching.")
    args, application_arguments = parser.parse_known_args()
    updater = Updater(ROOT)
    try:
        require_independent_python(ROOT)
        with Lease(ROOT / "startup/logs/launcher.lock"):
            if args.check_only:
                with redirect_stdout(sys.stderr):
                    update = updater.check()
                if sys.stdout is not None:
                    print(json.dumps(asdict(update) if update is not None else None))
                return 0
            return startup(updater, application_arguments, skip_check=args.skip_update_check, repair=args.repair)
    except BusyError as error:
        ask(updater, {"kind": "message", "title": "FITS is already open", "message": str(error) + "\nClose that instance before updating."})
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        updater.message(f"Launcher failed: {error}")
        ask(updater, {"kind": "message", "title": "FITS launcher error",
                      "message": f"{error}\n\nDetails: startup/logs/update.log\n"
                                 "Run the installer again if necessary."})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
