"""Installer safety checks without installing dependencies or changing user menus."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


STARTUP = Path(__file__).resolve().parents[2] / "startup"


@pytest.fixture
def setup_module(monkeypatch):
    monkeypatch.syspath_prepend(str(STARTUP))
    spec = importlib.util.spec_from_file_location("fits_installer", STARTUP / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        capture_output=True, text=True,
    ).stdout


@pytest.fixture
def checkout(tmp_path):
    """A real parent/submodule pair, entirely local and with spaces in its path."""
    source = tmp_path / "module source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.email", "test@example.org")
    git(source, "config", "user.name", "Installer Test")
    (source / "module.py").write_text("value = 1\n")
    git(source, "add", ".")
    git(source, "commit", "-qm", "initial")
    root = tmp_path / "FITS checkout"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Installer Test")
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", str(source), "example")
    git(root, "commit", "-qam", "module")
    return root


def test_dirty_module_is_not_changed(setup_module, checkout, monkeypatch):
    monkeypatch.setattr(setup_module.shutil, "which", lambda name: name)
    edited = checkout / "example" / "module.py"
    edited.write_text("uncommitted work\n")
    installer = setup_module.Installer(checkout)
    with pytest.raises(RuntimeError, match="local changes"):
        installer.check_checkout()
    assert edited.read_text() == "uncommitted work\n"


def test_different_module_commit_is_not_changed(setup_module, checkout, monkeypatch):
    monkeypatch.setattr(setup_module.shutil, "which", lambda name: name)
    module = checkout / "example"
    git(module, "config", "user.email", "test@example.org")
    git(module, "config", "user.name", "Installer Test")
    (module / "module.py").write_text("value = 2\n")
    git(module, "commit", "-qam", "local module work")
    head = git(module, "rev-parse", "HEAD")
    with pytest.raises(RuntimeError, match="differs"):
        setup_module.Installer(checkout).check_checkout()
    assert git(module, "rev-parse", "HEAD") == head


def test_missing_submodule_can_pass_preflight(setup_module, checkout, monkeypatch):
    monkeypatch.setattr(setup_module.shutil, "which", lambda name: name)
    git(checkout, "submodule", "deinit", "example")
    setup_module.Installer(checkout).check_checkout()


def test_subprocess_failure_is_logged_and_stops(setup_module, tmp_path):
    installer = setup_module.Installer(tmp_path)
    with pytest.raises(RuntimeError, match="Command failed"):
        installer.run(sys.executable, "-c", "print('download failed'); raise SystemExit(7)")
    assert "download failed" in installer.log_path.read_text()


def test_sync_failure_does_not_create_shortcut(setup_module, tmp_path, monkeypatch):
    installer = setup_module.Installer(tmp_path)
    monkeypatch.setattr(installer, "check_checkout", lambda: None)
    commands = []

    def run(*command):
        commands.append(command)
        if command[:2] == ("uv", "sync"):
            raise RuntimeError("sync failed")
        return ""

    monkeypatch.setattr(installer, "run", run)
    monkeypatch.setattr(setup_module, "install_shortcut", lambda *a, **k: pytest.fail("shortcut created"))
    with pytest.raises(RuntimeError, match="sync failed"):
        installer.install(no_shortcut=False)
    assert commands[-1] == ("uv", "sync", "--python", "3.12")


@pytest.fixture
def shortcuts(setup_module, monkeypatch):
    import shortcuts
    monkeypatch.setattr(shortcuts.shutil, "which", lambda name: None)
    monkeypatch.setattr(shortcuts.sys, "platform", "linux")
    return shortcuts


def make_install(root):
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").touch()
    (root / "assets").mkdir()
    (root / "assets" / "fits_logo.png").touch()
    (root / "startup").mkdir()
    (root / "startup" / "launch_linux.sh").touch()


def test_shortcut_replacement_requires_consent(shortcuts, tmp_path, monkeypatch):
    root = tmp_path / "new FITS"
    make_install(root)
    menu = tmp_path / "menu"
    menu.mkdir()
    shortcut = menu / "fits.desktop"
    original = "[Desktop Entry]\nPath=/old/fits\n"
    shortcut.write_text(original)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    shortcuts.install_shortcut(root, output_dir=menu)
    assert shortcut.read_text() == original
    monkeypatch.setattr("builtins.input", lambda prompt: "yes")
    shortcuts.install_shortcut(root, output_dir=menu)
    assert f"Path={root}" in shortcut.read_text()
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("prompt on same checkout"))
    shortcuts.install_shortcut(root, output_dir=menu)


def test_desktop_command_quotes_special_paths(shortcuts, tmp_path):
    root = tmp_path / 'FITS with spaces $`"%'
    entry = shortcuts.desktop_entry(root)
    command = next(line for line in entry.splitlines() if line.startswith("Exec="))
    assert command.startswith('Exec="') and command.endswith('/startup/launch_linux.sh"')
    assert "%%" in command
    assert '\\\\$' in command and '\\\\`' in command and '\\\\"' in command


@pytest.mark.skipif(sys.platform != "linux", reason="Linux entry-file integration")
def test_linux_entry_runs_installation_from_another_directory(checkout, tmp_path):
    """Exercise bootstrap/sync/verify/menu wiring with a fake uv, without downloads."""
    shutil.copytree(STARTUP, checkout / "startup", ignore=shutil.ignore_patterns("__pycache__", "logs"))
    repository = STARTUP.parent
    shutil.copy(repository / "install_linux.sh", checkout / "install_linux.sh")
    (checkout / "assets").mkdir()
    (checkout / "assets" / "fits_logo.png").touch()
    (checkout / "startup" / "verify.py").write_text("print('Verification invoked')\n")
    tools = tmp_path / "tools"
    tools.mkdir()
    uv = tools / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1] == 'run':\n"
        "    os.execv(sys.executable, [sys.executable, *sys.argv[6:]])\n"
        "if sys.argv[1:3] == ['python', 'find']:\n"
        "    print(sys.executable)\n"
        "    raise SystemExit(0)\n"
        "assert sys.argv[1:] == ['sync', '--python', '3.12']\n"
        "environment = pathlib.Path(os.environ['UV_PROJECT_ENVIRONMENT'])\n"
        "(environment / 'bin').mkdir(parents=True, exist_ok=True)\n"
        "(environment / 'bin' / 'python').symlink_to(sys.executable)\n"
        "pathlib.Path('uv.lock').write_text('simulated lockfile')\n"
    )
    uv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(tools) + os.pathsep + environment["PATH"]
    environment["XDG_DATA_HOME"] = str(tmp_path / "user data")
    result = subprocess.run(
        ["bash", str(checkout / "install_linux.sh")], cwd=tmp_path,
        env=environment, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Verification invoked" in result.stdout
    assert "FITS installation complete" in result.stdout
    shortcut = Path(environment["XDG_DATA_HOME"]) / "applications" / "fits.desktop"
    assert f"Path={checkout}" in shortcut.read_text()
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", str(shortcut)], check=True)
