"""Check FIScH's latest GitHub release and apply it without importing FIScH."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from locking import Lease
from setup import Installer
from state import command_environment, module_heads, record_installation, require_independent_python, show_project_files, write_json


@dataclass
class Release:
    version: str
    description: str


@dataclass
class Update:
    branch: str
    before: str
    target: str
    description: str
    blocked: str = ""
    release: str = ""
    current_version: str = ""


class Updater(Installer):
    def __init__(self, root: Path) -> None:
        super().__init__(root.resolve())
        self.log_path = self.root / "startup/logs/update.log"
        self.pending = self.root / "startup/logs/update-pending.json"

    def git(self, *arguments: str, timeout: float = 15, check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *arguments], cwd=self.root, env=command_environment(self.root),
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or f"Git failed: {' '.join(arguments)}")
        return result

    def local_changes(self, *, ignore_module_commits: bool = False) -> str:
        arguments = ["status", "--porcelain", "--untracked-files=normal"]
        arguments.append("--ignore-submodules=all" if ignore_module_commits else "--ignore-submodules=none")
        return self.git(*arguments).stdout.strip()

    def check(self) -> Update | None:
        """
        Fetch only the published release tag, leaving all checkouts untouched.
        """
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
        release = self._latest_release(remote)
        if release is None:
            return None
        self.git("fetch", "--no-tags", "--no-recurse-submodules", "--", remote, f"refs/tags/{release.version}", timeout=10)
        target = self.git("rev-parse", "FETCH_HEAD^{commit}").stdout.strip()
        if target == before:
            self.message(f"FIScH is up to date (release {release.version}).")
            return None
        if self.git("merge-base", "--is-ancestor", target, before, check=False).returncode == 0:
            self.message(f"Local FIScH commits are ahead of release {release.version}; leaving this checkout unchanged.")
            return None
        blocked = ""
        if self.git("merge-base", "--is-ancestor", before, target, check=False).returncode:
            blocked = "Local commits and the release have diverged. Reconcile them in Git before updating."
        changes = self.local_changes()
        if changes:
            blocked = "This checkout has local changes. Commit or save them before updating.\n" + changes
        current_version = tomllib.loads(self.git("show", f"{before}:pyproject.toml").stdout)["project"]["version"]
        return Update(branch, before, target, release.description, blocked, release.version, current_version)

    def _latest_release(self, remote: str) -> Release | None:
        """
        Read the upstream GitHub repository's latest published stable release.
        """
        url = self.git("remote", "get-url", remote).stdout.strip()
        repository = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?", url)
        if repository is None:
            self.message("Update check skipped: the upstream is not a GitHub repository.")
            return None
        request = Request(f"https://api.github.com/repos/{repository[1]}/releases/latest",
                          headers={"Accept": "application/vnd.github+json", "User-Agent": "FIScH-updater"},
                          )
        try:
            with urlopen(request, timeout=10) as response:
                release = json.load(response)
        except HTTPError as error:
            if error.code != 404:
                raise
            self.message("No published GitHub release is available.")
            return None
        tag = release["tag_name"]
        if release["draft"] or release["prerelease"] or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
            raise ValueError("The latest GitHub release must have a stable X.Y.Z tag.")
        return Release(tag, release.get("body") or "")

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
            raise RuntimeError("FIScH changed since the update check. Restart FIScH to check again.")
        if self.git("symbolic-ref", "--short", "HEAD").stdout.strip() != update.branch:
            raise RuntimeError("The FIScH branch changed since the update check.")
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
            raise RuntimeError("FIScH changed during an unfinished update. Reconcile it manually.")
        if state.get("repair_only") and before == target and self._modules_at_required_versions():
            self._synchronize_environment()
            self.pending.unlink()
            return
        if not state.get("repair_only") and self.local_changes(ignore_module_commits=True):
            raise RuntimeError("Local FIScH changes prevent resuming this update. Nothing will be discarded.")
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

    def _modules_at_required_versions(self) -> bool:
        """
        Allow environment-only repair when no submodule checkout needs to move.
        """
        statuses = self.git("submodule", "status", "--recursive").stdout.splitlines()
        return all(line.startswith(" ") for line in statuses) and self.module_heads() == self.module_heads(recorded=True)

    def _synchronize_environment(self) -> None:
        """
        Verify the current dependencies without modifying any source checkout.
        """
        self.message("Repairing the environment only; preserving local FIScH and submodule edits.")
        self.run("uv", "sync", "--python", "3.12")
        python = self.root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.run(str(python), str(self.root / "startup/verify.py"))
        record_installation(self.root)

    def synchronize(self) -> None:
        """
        Update FIScH dependencies and shortcuts without prompting about optional tools.
        """
        # Run the newly checked-out installer in independent Python. The GUI and
        # its Qt prompt have both exited before this process touches .venv.
        self.run(sys.executable, str(self.root / "startup/setup.py"), "--no-shortcut", "--without-tad")
        self.run(sys.executable, str(self.root / "startup/shortcuts.py"), "--refresh-existing")


def main() -> int:
    if os.name == "nt" and os.environ.get("FISCH_UPDATE_CONSOLE") == "1":
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
            updater.message("FIScH is ready. The launcher will now open the GUI.")
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
