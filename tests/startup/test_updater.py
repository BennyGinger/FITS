"""Exercise real local Git updates and interruptions without network/downloads."""

import importlib
import io
import json
from email.message import Message
import os
from pathlib import Path
import shutil
import subprocess
import sys
import stat
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from filelock import FileLock


STARTUP = Path(__file__).resolve().parents[2] / "startup"


def git(root, *arguments):
    return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(root: Path, message: str, *, publish: bool = False) -> str:
    """
    Commit test changes and optionally publish an annotated stable release tag.
    """
    git(root, "add", ".")
    git(root, "commit", "-qm", message)
    if publish:
        count = len(git(root, "tag", "--list").splitlines())
        git(root, "tag", "-a", f"5.0.{count}", "-m", message)
    return git(root, "rev-parse", "HEAD")


def initialize(root):
    root.mkdir()
    git(root, "init", "-qb", "main")
    git(root, "config", "user.name", "Updater Test")
    git(root, "config", "user.email", "test@example.org")


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(STARTUP))
    return importlib.import_module("updater"), importlib.import_module("launcher")


@pytest.fixture
def repositories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                 modules: tuple[ModuleType, ModuleType],
                 ) -> tuple[Path, Path]:
    """
    Use real local Git remotes with a simulated published-release lookup.
    """
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    remote = tmp_path / "upstream FIScH"
    initialize(remote)
    (remote / ".gitignore").write_text(".venv/\nstartup/logs/\n__pycache__/\n")
    (remote / "app.py").write_text("version = 1\n")
    (remote / "uv.lock").write_text("test lockfile\n")
    (remote / "pyproject.toml").write_text('[project]\nversion = "5.0.0"\n')
    commit(remote, "initial", publish=True)
    root = tmp_path / "local FIScH"
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.name", "Updater Test")
    git(root, "config", "user.email", "test@example.org")

    def latest_release(self: object, remote_name: str) -> object:
        """
        Simulate GitHub selecting the newest published release in the test remote.
        """
        return modules[0].Release(git(remote, "tag", "--sort=-version:refname").splitlines()[0], "Published release notes")

    monkeypatch.setattr(modules[0].Updater, "_latest_release", latest_release)
    return remote, root


def change_remote(remote: Path, message: str = "new FIScH", *, publish: bool = True) -> str:
    """
    Add an upstream commit, publishing a release unless explicitly disabled.
    """
    (remote / "app.py").write_text(message + "\n")
    return commit(remote, message, publish=publish)


def test_only_published_release_commits_are_offered(modules: tuple[ModuleType, ModuleType],
                                                 repositories: tuple[Path, Path],
                                                 monkeypatch: pytest.MonkeyPatch,
                                                 ) -> None:
    """
    Ignore unpublished commits and bare tags, then apply only the chosen release.
    """
    module, _ = modules
    remote, root = repositories
    engine = module.Updater(root)
    before = git(root, "rev-parse", "HEAD")
    change_remote(remote, "unreleased work", publish=False)
    git(remote, "tag", "99.0.0")
    monkeypatch.setattr(engine, "_latest_release", lambda remote_name: module.Release("5.0.0", "Initial release"))
    assert engine.check() is None
    target = change_remote(remote, "released work", publish=False)
    git(remote, "tag", "-a", "5.1.0", "-m", "FIScH 5.1.0")
    monkeypatch.setattr(engine, "_latest_release", lambda remote_name: module.Release("5.1.0", "## Changes\n\nReleased work"))
    change_remote(remote, "after release", publish=False)
    update = engine.check()
    assert update is not None
    assert update.before == before and update.target == target
    assert update.release == "5.1.0"
    assert update.current_version == "5.0.0"
    assert update.description == "## Changes\n\nReleased work"
    engine.prepare(update)
    monkeypatch.setattr(engine, "synchronize", lambda: None)
    engine.resume()
    assert git(root, "rev-parse", "HEAD") == target
    git(root, "fetch", "origin", "main")
    git(root, "merge", "--ff-only", "FETCH_HEAD")
    assert engine.check() is None


@pytest.mark.parametrize("url", ["https://github.com/BennyGinger/fisch.git",
                                "git@github.com:BennyGinger/fisch.git",
                                "ssh://git@github.com/BennyGinger/fisch.git",
                                "https://github.com/BennyGinger/fisch/",
                                ])
@pytest.mark.parametrize("kind", ["stable", "draft", "prerelease", "invalid-tag", "missing", "rate-limit"])
def test_github_release_lookup(modules: tuple[ModuleType, ModuleType], tmp_path: Path,
                              monkeypatch: pytest.MonkeyPatch, url: str, kind: str,
                              ) -> None:
    """
    Query GitHub releases with bounded requests and reject nonstable responses.
    """
    module, _ = modules
    root = tmp_path / "checkout"
    initialize(root)
    git(root, "remote", "add", "origin", url)
    engine = module.Updater(root)

    def open_release(request: Request, *, timeout: int) -> io.BytesIO:
        """
        Return a release response or simulate an HTTP failure without network access.
        """
        assert request.full_url == "https://api.github.com/repos/BennyGinger/fisch/releases/latest"
        assert timeout == 10
        if kind in ("missing", "rate-limit"):
            raise HTTPError(request.full_url, 404 if kind == "missing" else 403, kind, Message(), None)
        return io.BytesIO(json.dumps({"tag_name": "5.1.0rc1" if kind == "invalid-tag" else "5.1.0",
                                     "draft": kind == "draft", "prerelease": kind == "prerelease",
                                     "body": "## Changes\n\nRelease description from GitHub.",
                                     }).encode())

    monkeypatch.setattr(module, "urlopen", open_release)
    if kind == "stable":
        assert engine._latest_release("origin") == module.Release("5.1.0", "## Changes\n\nRelease description from GitHub.")
    elif kind == "missing":
        assert engine._latest_release("origin") is None
    elif kind == "rate-limit":
        with pytest.raises(HTTPError):
            engine._latest_release("origin")
    else:
        with pytest.raises(ValueError, match="stable X.Y.Z"):
            engine._latest_release("origin")


@pytest.mark.parametrize("error", [ValueError("invalid JSON"), HTTPError("https://api.github.com", 403, "rate limit", Message(), None)])
def test_failed_release_lookup_launches_current_version(modules: tuple[ModuleType, ModuleType],
                                                      repositories: tuple[Path, Path],
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      error: Exception,
                                                      ) -> None:
    """
    Preserve normal startup when the release service fails or returns invalid JSON.
    """
    module, launcher = modules
    _, root = repositories
    engine = module.Updater(root)
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)
    monkeypatch.setattr(engine, "_latest_release", MagicMock(side_effect=error))
    launches: list[bool] = []
    monkeypatch.setattr(launcher, "launch_gui", lambda *args: launches.append(True) or 0)
    monkeypatch.setattr(launcher, "ask", lambda *args: pytest.fail("offered an unavailable release"))
    assert launcher.startup(engine, []) == 0
    assert launches == [True]


def test_startup_prompt_uses_versions_and_release_description(modules: tuple[ModuleType, ModuleType],
                                                            repositories: tuple[Path, Path],
                                                            monkeypatch: pytest.MonkeyPatch,
                                                            ) -> None:
    """
    Pass version numbers and the unmodified release body to the update dialog.
    """
    module, launcher = modules
    remote, root = repositories
    change_remote(remote)
    description = "## Release highlights\n\n- Improved tracking.\n- Updated GUI."
    engine = module.Updater(root)
    monkeypatch.setattr(engine, "_latest_release", lambda remote: module.Release("5.0.1", description))
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)
    requests: list[dict[str, object]] = []
    monkeypatch.setattr(launcher, "ask", lambda updater, request: requests.append(request) or "current")
    monkeypatch.setattr(launcher, "launch_gui", lambda *args: 0)
    assert launcher.startup(engine, []) == 0
    assert len(requests) == 1
    assert requests[0]["message"] == "A newer version of FIScH is available: 5.0.1.\nThe current version installed is 5.0.0.\n\nWould you like to update?"
    assert requests[0]["release"] == "5.0.1"
    assert requests[0]["current_version"] == "5.0.0"
    assert requests[0]["details"] == description


def test_check_current_and_offer_fast_forward_without_changing_checkout(modules, repositories):
    module, _ = modules
    remote, root = repositories
    engine = module.Updater(root)
    before = git(root, "rev-parse", "HEAD")
    assert engine.check() is None
    target = change_remote(remote)
    update = engine.check()
    assert update.before == before and update.target == target
    assert not update.blocked
    assert update.description == "Published release notes"
    assert update.current_version == "5.0.0"
    assert git(root, "rev-parse", "HEAD") == before
    assert (root / "app.py").read_text() == "version = 1\n"


@pytest.mark.parametrize("kind", ["edit", "untracked", "diverged"])
def test_local_work_is_never_overwritten(modules, repositories, kind):
    module, _ = modules
    remote, root = repositories
    change_remote(remote)
    if kind == "edit":
        (root / "app.py").write_text("local work\n")
    elif kind == "untracked":
        (root / "notes.txt").write_text("local notes\n")
    else:
        (root / "app.py").write_text("local commit\n")
        commit(root, "local work")
    before = git(root, "rev-parse", "HEAD")
    engine = module.Updater(root)
    update = engine.check()
    assert update.blocked
    with pytest.raises(RuntimeError):
        engine.prepare(update)
    assert git(root, "rev-parse", "HEAD") == before
    assert not engine.pending.exists()


def test_apply_and_resume_exact_selected_commit(modules, repositories, monkeypatch):
    module, _ = modules
    remote, root = repositories
    engine = module.Updater(root)
    target = change_remote(remote)
    update = engine.check()
    engine.prepare(update)
    change_remote(remote, "later update not selected")
    calls = []

    def synchronize():
        calls.append("sync")
        if len(calls) == 1:
            raise RuntimeError("simulated interrupted dependency installation")

    monkeypatch.setattr(engine, "synchronize", synchronize)
    with pytest.raises(RuntimeError, match="interrupted"):
        engine.resume()
    assert git(root, "rev-parse", "HEAD") == target
    assert engine.pending.exists()
    engine.resume()
    assert calls == ["sync", "sync"]
    assert git(root, "rev-parse", "HEAD") == target
    assert not engine.pending.exists()


def test_resume_refuses_new_local_edits(modules, repositories, monkeypatch):
    module, _ = modules
    remote, root = repositories
    engine = module.Updater(root)
    change_remote(remote)
    engine.prepare(engine.check())
    (root / "app.py").write_text("new local work")
    monkeypatch.setattr(engine, "synchronize", lambda: pytest.fail("synchronized over local work"))
    with pytest.raises(RuntimeError, match="Local FIScH changes"):
        engine.resume()
    assert (root / "app.py").read_text() == "new local work"


def test_changed_branch_is_not_updated(modules, repositories):
    module, _ = modules
    remote, root = repositories
    change_remote(remote)
    engine = module.Updater(root)
    update = engine.check()
    git(root, "checkout", "-qb", "experiment")
    with pytest.raises(RuntimeError, match="branch changed"):
        engine.prepare(update)
    assert engine.check() is None


@pytest.mark.parametrize("repair_only", [True, False])
def test_dirty_pinned_submodule_allows_only_environment_repair(modules: tuple[ModuleType, ModuleType],
                                                              repositories: tuple[Path, Path],
                                                              tmp_path: Path,
                                                              monkeypatch: pytest.MonkeyPatch,
                                                              repair_only: bool,
                                                              ) -> None:
    """
    Preserve local module work during dependency repair while still refusing source updates.
    """
    module, _ = modules
    remote, root = repositories
    source = tmp_path / "module"
    initialize(source)
    (source / "module.py").write_text("original module")
    pin = commit(source, "module")
    git(remote, "submodule", "add", str(source), "example")
    commit(remote, "include module", publish=True)
    engine = module.Updater(root)
    monkeypatch.setattr(engine, "synchronize", lambda: None)
    engine.prepare(engine.check())
    engine.resume()
    import state
    state.record_installation(root)
    before = git(root, "rev-parse", "HEAD")
    if repair_only:
        (root / "uv.lock").write_text("changed dependencies")
        engine.prepare_repair()
        (root / "app.py").write_text("local FIScH work")
    else:
        change_remote(remote)
        engine.prepare(engine.check())
    edited = root / "example/module.py"
    untracked = root / "example/new.py"
    edited.write_text("local module work")
    untracked.write_text("new module work")
    calls: list[tuple[str, ...]] = []

    def run(*command: str) -> str:
        """
        Permit only environment commands and simulate the environment's interpreter.
        """
        assert command[0] != "git"
        calls.append(command)
        python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
        return ""

    monkeypatch.setattr(engine, "run", run)
    if repair_only:
        engine.resume()
        assert calls[0] == ("uv", "sync", "--python", "3.12")
        assert calls[1][-1] == str(root / "startup/verify.py")
        assert not engine.pending.exists()
        assert not state.needs_repair(root)
        assert (root / "app.py").read_text() == "local FIScH work"
    else:
        with pytest.raises(RuntimeError, match="Local submodule edits"):
            engine.resume()
        assert not calls
        assert engine.pending.exists()
    assert git(root, "rev-parse", "HEAD") == before
    assert git(root / "example", "rev-parse", "HEAD") == pin
    assert edited.read_text() == "local module work"
    assert untracked.read_text() == "new module work"


def test_failed_environment_verification_keeps_repair_pending(modules: tuple[ModuleType, ModuleType],
                                                              repositories: tuple[Path, Path],
                                                              monkeypatch: pytest.MonkeyPatch,
                                                              ) -> None:
    """
    Write a new installation receipt only after the repaired environment verifies successfully.
    """
    module, _ = modules
    _, root = repositories
    import state
    state.record_installation(root)
    receipt = root / "startup/logs/installed.json"
    before = receipt.read_bytes()
    engine = module.Updater(root)
    engine.prepare_repair()

    def run(*command: str) -> str:
        """
        Simulate successful synchronization followed by a failing import check.
        """
        if command[-1] == str(root / "startup/verify.py"):
            raise RuntimeError("verification failed")
        return ""

    monkeypatch.setattr(engine, "run", run)
    with pytest.raises(RuntimeError, match="verification failed"):
        engine.resume()
    assert engine.pending.exists()
    assert receipt.read_bytes() == before


def test_new_submodule_is_initialized_and_existing_one_is_pinned(modules, repositories, tmp_path, monkeypatch):
    module, _ = modules
    remote, root = repositories
    source = tmp_path / "module upstream"
    initialize(source)
    (source / "module.py").write_text("version = 1\n")
    first = commit(source, "module one")
    git(remote, "submodule", "add", str(source), "example module")
    commit(remote, "add module", publish=True)
    engine = module.Updater(root)
    monkeypatch.setattr(engine, "synchronize", lambda: None)
    engine.prepare(engine.check())
    engine.resume()
    assert git(root / "example module", "rev-parse", "HEAD") == first
    (source / "module.py").write_text("version = 2\n")
    second = commit(source, "module two")
    # A module-only push does not offer a FIScH update or fetch module remotes.
    assert engine.check() is None
    assert git(root / "example module", "rev-parse", "HEAD") == first
    git(remote / "example module", "fetch")
    git(remote / "example module", "checkout", second)
    commit(remote, "adopt module two", publish=True)
    engine.prepare(engine.check())
    engine.resume()
    assert git(root / "example module", "rev-parse", "HEAD") == second


@pytest.mark.parametrize("route", ["interrupted", "manual-pull"])
def test_crash_between_parent_and_module_update_is_repairable(modules, repositories, tmp_path, monkeypatch, route):
    module, _ = modules
    remote, root = repositories
    source = tmp_path / "module"
    initialize(source)
    (source / "module.py").write_text("one")
    commit(source, "one")
    git(remote, "submodule", "add", str(source), "example")
    commit(remote, "add example", publish=True)
    engine = module.Updater(root)
    monkeypatch.setattr(engine, "synchronize", lambda: None)
    engine.prepare(engine.check())
    engine.resume()
    import state
    state.record_installation(root)
    (source / "module.py").write_text("two")
    second = commit(source, "two")
    git(remote / "example", "fetch")
    git(remote / "example", "checkout", second)
    commit(remote, "adopt two", publish=True)
    update = engine.check()
    if route == "interrupted":
        engine.prepare(update)
    git(root, "merge", "--ff-only", update.target)
    if route == "manual-pull":
        engine.prepare_repair()
    engine.resume()
    assert git(root / "example", "rev-parse", "HEAD") == second


def test_offline_or_skip_check_opens_current_without_mutating(modules, repositories, monkeypatch):
    module, launcher = modules
    _, root = repositories
    engine = module.Updater(root)
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)
    monkeypatch.setattr(engine, "check", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    launches = []
    monkeypatch.setattr(launcher, "launch_gui", lambda updater, args: launches.append(args) or 0)
    monkeypatch.setattr(launcher, "ask", lambda *args: pytest.fail("unexpected prompt"))
    assert launcher.startup(engine, ["--example"]) == 0
    monkeypatch.setattr(engine, "check", lambda: pytest.fail("network check was not skipped"))
    assert launcher.startup(engine, [], skip_check=True) == 0
    assert launches == [["--example"], []]


@pytest.mark.parametrize("choice", ["current", "update"])
def test_startup_respects_choice_and_waits_for_update(modules, repositories, monkeypatch, choice):
    module, launcher = modules
    remote, root = repositories
    before = git(root, "rev-parse", "HEAD")
    target = change_remote(remote)
    engine = module.Updater(root)
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)
    monkeypatch.setattr(launcher, "ask", lambda *args: choice)
    monkeypatch.setattr(engine, "synchronize", lambda: None)

    def progress(updater, *, repair):
        updater.resume()
        return True

    monkeypatch.setattr(launcher, "run_progress", progress)
    launches = []
    monkeypatch.setattr(launcher, "launch_gui", lambda updater, args: launches.append(git(root, "rev-parse", "HEAD")) or 0)
    assert launcher.startup(engine, []) == 0
    assert launches == [target if choice == "update" else before]


def test_application_lock_blocks_update_and_direct_gui_lock(modules, repositories):
    _, launcher = modules
    _, root = repositories
    path = root / "startup/logs/application.lock"
    with launcher.Lease(path):
        with pytest.raises(Exception):
            FileLock(str(path), timeout=0).acquire()
    with FileLock(str(path), timeout=0):
        with pytest.raises(launcher.BusyError):
            with launcher.Lease(path):
                pytest.fail("acquired an in-use application lock")


def test_failed_update_does_not_open_gui(modules, repositories, monkeypatch):
    module, launcher = modules
    remote, root = repositories
    change_remote(remote)
    engine = module.Updater(root)
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)
    monkeypatch.setattr(launcher, "ask", lambda *args: "update")
    monkeypatch.setattr(launcher, "run_progress", lambda *args, **kwargs: False)
    monkeypatch.setattr(launcher, "launch_gui", lambda *args: pytest.fail("opened an incomplete installation"))
    assert launcher.startup(engine, []) == 1
    assert engine.pending.exists()


def test_parent_moving_after_check_is_rejected(modules, repositories):
    module, _ = modules
    remote, root = repositories
    change_remote(remote)
    engine = module.Updater(root)
    update = engine.check()
    (root / "local.txt").write_text("local work")
    commit(root, "local commit after check")
    with pytest.raises(RuntimeError, match="changed since"):
        engine.prepare(update)


def test_fetch_is_bounded_and_does_not_recurse_modules(modules, repositories, monkeypatch):
    module, _ = modules
    _, root = repositories
    engine = module.Updater(root)
    real_git = engine.git

    def git_call(*arguments, **kwargs):
        if arguments[0] == "fetch":
            assert "--no-recurse-submodules" in arguments
            assert kwargs["timeout"] == 10
            raise subprocess.TimeoutExpired("git fetch", 10)
        return real_git(*arguments, **kwargs)

    monkeypatch.setattr(engine, "git", git_call)
    with pytest.raises(subprocess.TimeoutExpired):
        engine.check()


def test_bootstrap_lookup_excludes_project_environment(modules, repositories, monkeypatch):
    import state
    _, root = repositories
    python = Path(sys.executable)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=str(python) + "\n")

    monkeypatch.setattr(state.subprocess, "run", run)
    assert state.record_bootstrap(root) == python
    assert "--system" in calls[0] and "--managed-python" in calls[0]
    fake_python = root / ".venv/bin/python"
    fake_python.parent.mkdir(parents=True)
    fake_python.touch()
    monkeypatch.setattr(state.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=str(fake_python)))
    with pytest.raises(RuntimeError, match="independent"):
        state.record_bootstrap(root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake uv executable")
def test_update_runs_real_installer_with_simulated_dependencies(modules, repositories, tmp_path, monkeypatch):
    module, _ = modules
    remote, root = repositories
    shutil.copytree(STARTUP, remote / "startup", ignore=shutil.ignore_patterns("logs", "__pycache__", "tools"))
    (remote / "assets").mkdir()
    (remote / "assets/fisch_icon.png").touch()
    (remote / "startup/verify.py").write_text("print('Backend verification reached')\n")
    target = commit(remote, "include installer", publish=True)
    tools = tmp_path / "tools"
    tools.mkdir()
    uv = tools / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1:3] == ['python', 'find']:\n"
        "    print(sys.executable)\n"
        "    raise SystemExit(0)\n"
        "assert sys.argv[1:] == ['sync', '--python', '3.12']\n"
        "environment = pathlib.Path(os.environ['UV_PROJECT_ENVIRONMENT'])\n"
        "(environment / 'bin').mkdir(parents=True, exist_ok=True)\n"
        "(environment / 'bin/python').symlink_to(sys.executable)\n"
    )
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "menu"))
    engine = module.Updater(root)
    engine.prepare(engine.check())
    engine.resume()
    assert git(root, "rev-parse", "HEAD") == target
    assert (root / "startup/logs/bootstrap-python.txt").exists()
    assert (root / "startup/logs/installed.json").exists()
    assert "Backend verification reached" in (root / "startup/logs/install.log").read_text()
    assert not engine.pending.exists()


def test_independent_interpreter_guard(modules, repositories, monkeypatch):
    import state
    _, root = repositories
    monkeypatch.setattr(state.sys, "executable", str(root / ".venv/bin/python"))
    with pytest.raises(RuntimeError, match="outside"):
        state.require_independent_python(root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher and symlink test")
def test_supervisor_shell_launches_current_and_exits_with_gui(modules, repositories, monkeypatch, tmp_path):
    _, launcher = modules
    _, root = repositories
    shutil.copytree(STARTUP, root / "startup", ignore=shutil.ignore_patterns("logs", "__pycache__", "tools"))
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    logs = root / "startup/logs"
    logs.mkdir()
    (logs / "bootstrap-python.txt").write_text(sys.executable)
    package = root / "src/fisch/gui"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").touch()
    (package / "__init__.py").touch()
    (package / "main.py").write_text("import sys\nprint('GUI finished', sys.argv[1:])\n")
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    before_fetch = (root / ".git/FETCH_HEAD").read_bytes() if (root / ".git/FETCH_HEAD").exists() else None
    result = subprocess.run(
        ["bash", str(root / "startup/launch_linux.sh"), "--skip-update-check", "--demo-step-delay", "3"],
        cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GUI finished ['--demo-step-delay', '3']" in (logs / "launcher.log").read_text()
    after_fetch = (root / ".git/FETCH_HEAD").read_bytes() if (root / ".git/FETCH_HEAD").exists() else None
    assert before_fetch == after_fetch
    with launcher.Lease(logs / "launcher.lock"):
        pass  # No orphaned supervisor keeps the session locked after GUI exit.


def test_direct_gui_holds_and_releases_updater_compatible_lock(modules, tmp_path):
    _, launcher = modules
    lock = tmp_path / "application.lock"
    code = (
        "import sys, time\n"
        "from fisch.gui import main\n"
        "sys.argv = ['fisch-gui']\n"
        "def run(arguments, qt_arguments):\n"
        "    print('holding lease', flush=True)\n"
        "    time.sleep(0.5)\n"
        "main._run_gui = run\n"
        "main.main()\n"
    )
    environment = os.environ.copy()
    environment["FISCH_APPLICATION_LOCK"] = str(lock)
    process = subprocess.Popen([sys.executable, "-c", code], env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "holding lease"
        with pytest.raises(launcher.BusyError):
            with launcher.Lease(lock):
                pytest.fail("updater acquired a running GUI's lease")
        assert process.wait(timeout=10) == 0
        with launcher.Lease(lock):
            pass
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_legacy_hidden_configs_are_made_visible(modules, monkeypatch):
    import state
    root = MagicMock(spec=Path)
    files = {}
    for name in ("pyproject.toml", "uv.lock"):
        path = MagicMock(spec=Path)
        path.configure_mock(**{"__str__.return_value": "C:\\fits\\" + name})
        path.exists.return_value = True
        path.stat.return_value = SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_READONLY)
        files[name] = path
    root.__truediv__.side_effect = files.__getitem__
    monkeypatch.setattr(state, "os", SimpleNamespace(name="nt"))
    commands = []
    monkeypatch.setattr(state.subprocess, "run", lambda command, **kwargs: commands.append(command))
    state.show_project_files(root)
    assert [command[1] for command in commands] == ["-H", "-H"]
    assert all(command[0] == "attrib.exe" for command in commands)


def test_refusing_repair_does_not_change_or_launch(modules, repositories, monkeypatch):
    module, launcher = modules
    _, root = repositories
    updater = module.Updater(root)
    monkeypatch.setattr(launcher, "needs_repair", lambda root: True)
    monkeypatch.setattr(launcher, "ask", lambda *args: "cancel")
    monkeypatch.setattr(launcher, "launch_gui", lambda *args: pytest.fail("launched incomplete environment"))
    monkeypatch.setattr(launcher, "run_progress", lambda *a, **k: pytest.fail("repair was not accepted"))
    assert launcher.startup(updater, [], skip_check=True) == 0
    assert not updater.pending.exists()


def test_check_only_prints_valid_json_and_does_not_launch(modules, repositories, monkeypatch, capsys):
    import json
    _, launcher = modules
    _, root = repositories
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["launcher.py", "--check-only"])
    monkeypatch.setattr(launcher, "launch_gui", lambda *args: pytest.fail("launched in check-only mode"))
    assert launcher.main() == 0
    assert json.loads(capsys.readouterr().out) is None


def test_broken_qt_uses_independent_native_choice(modules, repositories, monkeypatch):
    module, launcher = modules
    _, root = repositories
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    updater = module.Updater(root)
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, stdout="", stderr="No module named PySide6"))
    monkeypatch.setattr(launcher, "native_choice", lambda request: "repair")
    assert launcher.ask(updater, {"kind": "repair", "message": "Repair?"}) == "repair"
    assert "No module named PySide6" in updater.log_path.read_text()


@pytest.mark.parametrize("receipt_kind", ["missing", "stale", "verified"])
def test_terminal_success_requires_current_verification_receipt(modules, repositories, monkeypatch, receipt_kind):
    import state
    module, launcher = modules
    _, root = repositories
    updater = module.Updater(root)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(launcher, "needs_repair", lambda root: False)

    def run(command, **kwargs):
        if os.name == "nt":
            assert kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE
        token = command[command.index("--result-token") + 1]
        if receipt_kind != "missing":
            state.write_json(updater.log_path.parent / "update-result.json", {
                "token": token if receipt_kind == "verified" else "an-older-update", "ready": True,
            })
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.run_progress(updater, repair=True) is (receipt_kind == "verified")


def test_receipt_detects_changed_dependencies_but_not_code(modules, repositories):
    import state
    _, root = repositories
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    state.record_installation(root)
    assert not state.needs_repair(root)
    (root / "app.py").write_text("code changes only")
    assert not state.needs_repair(root)
    (root / "uv.lock").write_text("changed dependencies")
    assert state.needs_repair(root)


@pytest.mark.parametrize("platform", ["nt", "posix"])
def test_background_startup_commands_do_not_open_consoles(modules, tmp_path, monkeypatch, platform):
    """Hide Git and bootstrap probes while retaining their captured results on both OSes."""
    import state
    module, _ = modules
    platform_os = SimpleNamespace(**vars(os))
    platform_os.name = platform
    monkeypatch.setattr(state, "os", platform_os)
    monkeypatch.setattr(module, "os", platform_os)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    calls = []
    python = tmp_path.parent / "managed python" / "python.exe"
    python.parent.mkdir(exist_ok=True)
    python.touch()

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ["uv", "python"]:
            output = str(python) + "\n"
        elif command[:2] == ["git", "ls-tree"]:
            output = b"160000 commit abc\tmodule\0"
        elif command[:3] == ["git", "submodule", "foreach"]:
            output = "module\0abc\0"
        else:
            output = "main\n"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    engine = module.Updater(tmp_path)
    assert engine.git("symbolic-ref", "--short", "HEAD").stdout == "main\n"
    assert state.dependency_signature(tmp_path)
    assert state.module_heads(tmp_path) == {"module": "abc"}
    assert state.record_bootstrap(tmp_path) == python
    assert len(calls) == 4
    for command, kwargs in calls:
        assert kwargs["creationflags"] == (subprocess.CREATE_NO_WINDOW if platform == "nt" else 0)
        assert kwargs["capture_output"] is True
