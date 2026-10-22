"""Check FITS's upstream branch and apply a selected update without importing FITS."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from locking import Lease
from setup import Installer
from state import command_environment, module_heads, require_independent_python, show_project_files, write_json


@dataclass
class Update:
    branch: str
    before: str
    target: str
    summary: str
    blocked: str = ""


class Updater(Installer):
    def __init__(self, root: Path) -> None:
        super().__init__(root.resolve())
        self.log_path = self.root / "startup/logs/update.log"
        self.pending = self.root / "startup/logs/update-pending.json"

    def git(self, *arguments: str, timeout: float = 15, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *arguments], cwd=self.root, env=command_environment(self.root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Git failed: {' '.join(arguments)}")
        return result

    def local_changes(self, *, ignore_module_commits: bool = False) -> str:
        arguments = ["status", "--porcelain", "--untracked-files=normal"]
        arguments.append("--ignore-submodules=all" if ignore_module_commits else "--ignore-submodules=none")
        return self.git(*arguments).stdout.strip()

    def check(self) -> Update | None:
        """Fetch only FITS, leaving the checkout and every module untouched."""
        branch = self.git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
        if branch not in ("main", "master"):
            self.message("Update check skipped: this is not a main/master branch checkout.")
            return None
        remote = self.git("config", "--get", f"branch.{branch}.remote", check=False).stdout.strip()
        reference = self.git("config", "--get", f"branch.{branch}.merge", check=False).stdout.strip()
        if not remote or remote == "." or reference not in ("refs/heads/main", "refs/heads/master"):
            self.message("Update check skipped: no main/master upstream is configured.")
            return None
        before = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("fetch", "--no-tags", "--no-recurse-submodules", "--", remote, reference, timeout=10)
        target = self.git("rev-parse", "FETCH_HEAD^{commit}").stdout.strip()
        if target == before:
            self.message("FITS is up to date.")
            return None
        if self.git("merge-base", "--is-ancestor", target, before, check=False).returncode == 0:
            self.message("Local FITS commits are ahead of the upstream; leaving this checkout unchanged.")
            return None
        blocked = ""
        if self.git("merge-base", "--is-ancestor", before, target, check=False).returncode:
            blocked = "Local and upstream commits have diverged. Reconcile them in Git before updating."
        changes = self.local_changes()
        if changes:
            blocked = "This checkout has local changes. Commit or save them before updating.\n" + changes
        summary = self.git("log", "--format=%h %s", "-8", f"{before}..{target}").stdout.strip()
        return Update(branch, before, target, summary, blocked)

    def module_heads(self, *, recorded: bool = False) -> dict[str, str]:
        return module_heads(self.root, recorded=recorded)

    def prepare_repair(self) -> None:
        """Retain the last installed module pins when repairing a manual pull."""
        current = self.git("rev-parse", "HEAD").stdout.strip()
        branch = self.git("symbolic-ref", "--short", "HEAD").stdout.strip()
        receipt = self.root / "startup/logs/installed.json"
        modules = json.loads(receipt.read_text(encoding="utf-8")).get("modules", {}) if receipt.exists() else {}
        write_json(self.pending, {
            "branch": branch, "before": current, "target": current,
            "modules_before": modules, "repair_only": True,
        })

    def prepare(self, update: Update) -> None:
        if self.pending.exists():
            raise RuntimeError("An unfinished update must be repaired first.")
        if update.blocked or self.local_changes():
            raise RuntimeError(update.blocked or "Local changes prevent automatic updating.")
        if self.git("rev-parse", "HEAD").stdout.strip() != update.before:
            raise RuntimeError("FITS changed since the update check. Restart FITS to check again.")
        if self.git("symbolic-ref", "--short", "HEAD").stdout.strip() != update.branch:
            raise RuntimeError("The FITS branch changed since the update check.")
        write_json(self.pending, {
            "branch": update.branch, "before": update.before, "target": update.target,
            "modules_before": self.module_heads(),
        })

    def resume(self) -> None:
        """Resume only the selected fast-forward; never reset, stash, or use --remote."""
        state = json.loads(self.pending.read_text(encoding="utf-8"))
        before, target, branch = state["before"], state["target"], state["branch"]
        if not all(re.fullmatch(r"[0-9a-f]{40,64}", value) for value in (before, target)):
            raise RuntimeError("The saved update contains an invalid commit identifier.")
        if self.git("symbolic-ref", "--short", "HEAD").stdout.strip() != branch:
            raise RuntimeError("The branch changed during an unfinished update. Reconcile it manually.")
        current = self.git("rev-parse", "HEAD").stdout.strip()
        if current not in (before, target):
            raise RuntimeError("FITS changed during an unfinished update. Reconcile it manually.")
        if not state.get("repair_only") and self.local_changes(ignore_module_commits=True):
            raise RuntimeError("Local FITS changes prevent resuming this update. Nothing will be discarded.")
        dirty = self.git(
            "submodule", "foreach", "--quiet", "--recursive",
            "git status --porcelain --untracked-files=normal --ignore-submodules=all",
        ).stdout.strip()
        if dirty:
            raise RuntimeError("Local submodule edits prevent resuming this update. Nothing will be discarded.")
        recorded = self.module_heads(recorded=True)
        original = state["modules_before"]
        for path, head in self.module_heads().items():
            if head not in (recorded.get(path), original.get(path)):
                raise RuntimeError(f"Submodule {path} has unexpected local commits; reconcile them manually.")
        if current != target:
            self.run("git", "merge", "--ff-only", target)
        self.run("git", "submodule", "sync", "--recursive")
        self.run("git", "submodule", "update", "--init", "--recursive")
        self.synchronize()
        self.pending.unlink()

    def synchronize(self) -> None:
        # Run the newly checked-out installer in independent Python. The GUI and
        # its Qt prompt have both exited before this process touches .venv.
        self.run(sys.executable, str(self.root / "startup/setup.py"), "--no-shortcut")
        self.run(sys.executable, str(self.root / "startup/shortcuts.py"), "--refresh-existing")


def main() -> int:
    if os.name == "nt" and os.environ.get("FITS_UPDATE_CONSOLE") == "1":
        # A pythonw parent has no standard handles to inherit. Bind explicitly
        # to the new console so progress and the retry prompt remain visible.
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--repair", action="store_true", help="Synchronize the current version without fetching.")
    parser.add_argument("--result-token", help=argparse.SUPPRESS)
    args = parser.parse_args()
    updater = Updater(args.root)
    while True:
        try:
            require_independent_python(updater.root)
            with Lease(updater.root / "startup/logs/application.lock"):
                show_project_files(updater.root)
                if updater.pending.exists():
                    updater.resume()
                elif args.repair:
                    updater.prepare_repair()
                    updater.resume()
                else:
                    raise RuntimeError("There is no selected update to apply.")
            updater.message("FITS is ready. The launcher will now open the GUI.")
            if args.result_token:
                write_json(updater.root / "startup/logs/update-result.json", {"token": args.result_token, "ready": True})
            return 0
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
            updater.message(f"Update/repair failed: {error}\nLog: {updater.log_path}")
            if not sys.stdin or not sys.stdin.isatty():
                return 1
            if input("Fix the reported issue, then [R]etry, or press Enter to close: ").strip().lower() != "r":
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
