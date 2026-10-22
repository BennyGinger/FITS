"""Exercise real local Git updates and interruptions without network/downloads."""

import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from filelock import FileLock


STARTUP = Path(__file__).resolve().parents[2] / "startup"


def git(root, *arguments):
    return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(root, message):
    git(root, "add", ".")
    git(root, "commit", "-qm", message)
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
def repositories(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    remote = tmp_path / "upstream FITS"
    initialize(remote)
    (remote / ".gitignore").write_text(".venv/\nstartup/logs/\n__pycache__/\n")
    (remote / "app.py").write_text("version = 1\n")
    (remote / "uv.lock").write_text("test lockfile\n")
    commit(remote, "initial")
    root = tmp_path / "local FITS"
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.name", "Updater Test")
    git(root, "config", "user.email", "test@example.org")
    return remote, root


def change_remote(remote, message="new FITS"):
    (remote / "app.py").write_text(message + "\n")
    return commit(remote, message)


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
    assert "new FITS" in update.summary
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
    with pytest.raises(RuntimeError, match="Local FITS changes"):
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


def test_new_submodule_is_initialized_and_existing_one_is_pinned(modules, repositories, tmp_path, monkeypatch):
    module, _ = modules
    remote, root = repositories
    source = tmp_path / "module upstream"
    initialize(source)
    (source / "module.py").write_text("version = 1\n")
    first = commit(source, "module one")
    git(remote, "submodule", "add", str(source), "example module")
    commit(remote, "add module")
    engine = module.Updater(root)
    monkeypatch.setattr(engine, "synchronize", lambda: None)
    engine.prepare(engine.check())
    engine.resume()
    assert git(root / "example module", "rev-parse", "HEAD") == first
    (source / "module.py").write_text("version = 2\n")
    second = commit(source, "module two")
    # A module-only push does not offer a FITS update or fetch module remotes.
    assert engine.check() is None
    assert git(root / "example module", "rev-parse", "HEAD") == first
    git(remote / "example module", "fetch")
    git(remote / "example module", "checkout", second)
    commit(remote, "adopt module two")
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
    commit(remote, "add example")
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
    commit(remote, "adopt two")
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
    shutil.copytree(STARTUP, remote / "startup", ignore=shutil.ignore_patterns("logs", "__pycache__"))
    (remote / "assets").mkdir()
    (remote / "assets/fits_logo.png").touch()
    (remote / "startup/verify.py").write_text("print('Backend verification reached')\n")
    target = commit(remote, "include installer")
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
    shutil.copytree(STARTUP, root / "startup", ignore=shutil.ignore_patterns("logs", "__pycache__"))
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    logs = root / "startup/logs"
    logs.mkdir()
    (logs / "bootstrap-python.txt").write_text(sys.executable)
    package = root / "src/fits/gui"
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
        "from fits.gui import main\n"
        "sys.argv = ['fits-gui']\n"
        "def run(arguments, qt_arguments):\n"
        "    print('holding lease', flush=True)\n"
        "    time.sleep(0.5)\n"
        "main._run_gui = run\n"
        "main.main()\n"
    )
    environment = os.environ.copy()
    environment["FITS_APPLICATION_LOCK"] = str(lock)
    process = subprocess.Popen([sys.executable, "-c", code], env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
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
        path.__str__.return_value = "C:\\fits\\" + name
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
