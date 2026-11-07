"""Installer safety checks without installing dependencies or changing user menus."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import ModuleType

import pytest


STARTUP = Path(__file__).resolve().parents[2] / "startup"


@pytest.fixture
def setup_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """
    Load the standalone installer for isolated installation checks.
    """
    monkeypatch.syspath_prepend(str(STARTUP))
    spec = importlib.util.spec_from_file_location("fits_installer", STARTUP / "setup.py")
    assert spec is not None and spec.loader is not None
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


def test_older_module_is_fetched_and_updated_before_dependency_sync(setup_module: ModuleType,
                                                                  checkout: Path,
                                                                  monkeypatch: pytest.MonkeyPatch,
                                                                  ) -> None:
    """
    Repair a manual parent pull even when the required module commit is not local.
    """
    monkeypatch.setattr(setup_module.shutil, "which", lambda name: name)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    source = checkout.parent / "module source"
    (source / "module.py").write_text("value = 2\n")
    git(source, "commit", "-qam", "required by new FITS")
    required = git(source, "rev-parse", "HEAD").strip()
    git(checkout, "update-index", "--cacheinfo", "160000", required, "example")
    git(checkout, "commit", "-qm", "update required library")
    module = checkout / "example"
    missing = subprocess.run(["git", "-C", str(module), "cat-file", "-e", required], capture_output=True)
    assert missing.returncode != 0
    # A newer upstream library release need not belong to this FITS version.
    (source / "module.py").write_text("value = 3\n")
    git(source, "commit", "-qam", "later independent library release")
    installer = setup_module.Installer(checkout)
    original_run = installer.run
    commands: list[tuple[str, ...]] = []

    def run(*command: str) -> str:
        """
        Exercise real Git synchronization and stop before modifying an environment.
        """
        commands.append(command)
        if command[:2] == ("uv", "sync"):
            assert git(module, "rev-parse", "HEAD").strip() == required
            assert (module / "module.py").read_text() == "value = 2\n"
            raise RuntimeError("dependency sync reached")
        return original_run(*command)

    monkeypatch.setattr(installer, "run", run)
    with pytest.raises(RuntimeError, match="dependency sync reached"):
        installer.install(no_shortcut=True)
    update = ("git", "submodule", "update", "--init", "--recursive")
    assert commands.index(update) < commands.index(("uv", "sync", "--python", "3.12"))


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
    (root / "assets" / "fits_icon.png").touch()
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


def test_linux_shortcut_changes_icon_path_when_image_changes(shortcuts, tmp_path):
    """Refresh cached desktop icons without changing canonical asset filenames."""
    root = tmp_path / 'FITS'
    make_install(root)
    icon = root / 'assets/fits_icon.png'
    menu = tmp_path / 'menu'
    icon.write_bytes(b'first image')
    shortcuts.install_shortcut(root, output_dir=menu)
    entry = menu / 'fits.desktop'
    first = Path(next(line[5:] for line in entry.read_text().splitlines() if line.startswith('Icon=')))
    assert first.read_bytes() == b'first image'
    icon.write_bytes(b'replacement image')
    shortcuts.install_shortcut(root, output_dir=menu, refresh_only=True)
    second = Path(next(line[5:] for line in entry.read_text().splitlines() if line.startswith('Icon=')))
    assert second != first
    assert second.read_bytes() == icon.read_bytes()
    shortcuts.install_shortcut(root, output_dir=menu, refresh_only=True)
    assert f'Icon={second}' in entry.read_text()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux entry-file integration")
def test_linux_entry_runs_installation_from_another_directory(checkout: Path, tmp_path: Path) -> None:
    """
    Exercise bootstrap/sync/verify/menu wiring with a fake uv, without downloads.
    """
    shutil.copytree(STARTUP, checkout / "startup", ignore=shutil.ignore_patterns("__pycache__", "logs", "tools"))
    shutil.copy2(STARTUP.parent / "install_linux.sh", checkout / "install_linux.sh")
    (checkout / "assets").mkdir()
    (checkout / "assets" / "fits_icon.png").touch()
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


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux shell bootstrap')
@pytest.mark.parametrize('failure', ['missing_git', 'python_download'])
def test_linux_bootstrap_failure_is_reported(tmp_path, failure):
    tools = tmp_path / 'bin'
    tools.mkdir()
    bash = shutil.which('bash')
    assert bash
    (tools / 'dirname').symlink_to(shutil.which('dirname'))
    if failure == 'python_download':
        (tools / 'git').symlink_to(shutil.which('git'))
        uv = tools / 'uv'
        uv.write_text(f'#!{bash}\nexit 7\n')
        uv.chmod(0o755)
    result = subprocess.run(
        [bash, str(STARTUP.parent / 'install_linux.sh'), '--pause'],
        env={**os.environ, 'HOME': str(tmp_path), 'PATH': str(tools)},
        capture_output=True, text=True,
    )
    assert result.returncode == (1 if failure == 'missing_git' else 7)
    assert 'FITS installation failed' in result.stdout
    if failure == 'missing_git':
        assert 'Git is required' in result.stdout


@pytest.mark.skipif(os.name == 'nt', reason='Unix bootstrap with simulated download')
@pytest.mark.parametrize('entry', ['install_linux.sh', 'install_macos.sh'])
@pytest.mark.parametrize('mode', ['download', 'existing', 'download_failure'])
def test_unix_uv_bootstrap(tmp_path: Path, entry: str, mode: str) -> None:
    """
    Download/reuse uv and reach setup immediately, without network or shell edits.
    """
    root = tmp_path / 'FITS checkout'
    (root / 'startup').mkdir(parents=True)
    shutil.copy2(STARTUP.parent / entry, root / entry)
    shutil.copy2(STARTUP / 'install_unix.sh', root / 'startup/install_unix.sh')
    (root / 'startup/setup.py').write_text(
        "import pathlib, sys\npathlib.Path('setup-args').write_text(repr(sys.argv[1:]))\n"
    )
    home = tmp_path / 'user home'
    home.mkdir()
    tools = tmp_path / 'tools'
    tools.mkdir()
    for command in ('dirname', 'mktemp', 'rm', 'sh', 'mkdir', 'cp', 'chmod', 'git'):
        executable = shutil.which(command)
        assert executable is not None
        (tools / command).symlink_to(executable)
    fake_uv = tmp_path / 'fake uv'
    fake_uv.write_text(
        f'#!{sys.executable}\nimport sys\n'
        "assert sys.argv[1:] == ['python', 'find', '--system', '--managed-python', '3.12']\n"
        'print(sys.executable)\n'
    )
    fake_uv.chmod(0o755)
    if mode == 'existing':
        (tools / 'uv').symlink_to(fake_uv)
    curl = tools / 'curl'
    installer = (
        'mkdir -p "$UV_INSTALL_DIR"\n'
        'cp "$FITS_TEST_UV" "$UV_INSTALL_DIR/uv"\n'
        'chmod +x "$UV_INSTALL_DIR/uv"\n'
        'printf "%s" "$UV_NO_MODIFY_PATH" > "$HOME/profile-policy"\n'
    )
    curl.write_text(
        f'#!{sys.executable}\nimport pathlib, sys\n'
        f'pathlib.Path({str(home / "downloaded")!r}).touch()\n'
        + ('raise SystemExit(9)\n' if mode == 'download_failure' else
           f'pathlib.Path(sys.argv[sys.argv.index("-o") + 1]).write_text({installer!r})\n')
    )
    curl.chmod(0o755)
    bash = shutil.which('bash')
    assert bash is not None
    result = subprocess.run(
        [bash, str(root / entry), '--pause', '--without-tad'],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, 'HOME': str(home), 'PATH': str(tools), 'FITS_TEST_UV': str(fake_uv)},
    )
    assert 'uv is required by FITS' in result.stdout
    assert 'FITS does not manage its updates or removal' in result.stdout
    if mode == 'download_failure':
        assert result.returncode != 0
        assert not (root / 'setup-args').exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert (root / 'setup-args').read_text() == "['--without-tad']"
    assert (home / 'downloaded').exists() == (mode != 'existing')
    if mode == 'download':
        assert (home / 'profile-policy').read_text() == '1'


def test_macos_shortcut_runs_quoted_checkout_and_preserves_other_install(shortcuts, tmp_path, monkeypatch):
    monkeypatch.setattr(shortcuts.sys, 'platform', 'darwin')
    root = tmp_path / 'FITS spaces $`" and apostrophe\''
    (root / 'startup').mkdir(parents=True)
    (root / 'startup/launch_macos.sh').write_text('printf "%s" "$1"')
    menu = tmp_path / 'Applications'
    shortcuts.install_shortcut(root, output_dir=menu)
    shortcut = menu / 'FITS.command'
    result = subprocess.run(['bash', str(shortcut), 'hello'], capture_output=True, text=True, check=True)
    assert result.stdout == 'hello'
    original = shortcut.read_bytes()
    shortcuts.install_shortcut(tmp_path / 'other', output_dir=menu, refresh_only=True)
    assert shortcut.read_bytes() == original
    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    shortcuts.install_shortcut(tmp_path / 'other', output_dir=menu)
    assert shortcut.read_bytes() == original
    assert os.access(shortcut, os.X_OK)


def test_gui_environment_finds_downloaded_uv(setup_module, monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('PATH', '/usr/bin')
    environment = setup_module.command_environment(tmp_path)
    assert environment['PATH'].split(os.pathsep)[-1] == str(tmp_path / '.local/bin')


def test_macos_reaches_shared_installer(setup_module, monkeypatch):
    from unittest.mock import Mock
    monkeypatch.setattr(setup_module.sys, 'platform', 'darwin')
    monkeypatch.setattr(setup_module.sys, 'argv', ['setup.py', '--without-tad'])
    installer = Mock()
    monkeypatch.setattr(setup_module, 'Installer', lambda root: installer)
    monkeypatch.setattr(setup_module, 'require_independent_python', lambda root: None)
    monkeypatch.setattr(setup_module.subprocess, 'run', Mock())
    assert setup_module.main() == 0
    installer.install.assert_called_once_with(False)
