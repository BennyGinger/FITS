"""An intentional GUI termination must not trigger the launcher's repair offer."""

import importlib
from pathlib import Path
import subprocess
import sys

import pytest


def test_user_quit_does_not_offer_installation_repair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Pass a real intentional-quit subprocess status through the startup supervisor.
    """
    startup = Path(__file__).resolve().parents[2] / 'startup'
    monkeypatch.syspath_prepend(str(startup))
    launcher = importlib.import_module('launcher')
    updater = launcher.Updater(tmp_path)
    monkeypatch.setattr(launcher, 'needs_repair', lambda root: False)
    monkeypatch.setattr(launcher, 'ask', lambda *args: pytest.fail('Intentional quit must not offer repair.'))
    monkeypatch.setattr(launcher, 'run_progress', lambda *args, **kwargs: pytest.fail('Intentional quit must not synchronize dependencies.'))

    def quit_gui(*args: object) -> int:
        """
        Terminate only a disposable Python process using the actual Quit implementation.
        """
        return subprocess.run([sys.executable, '-c',
                               'from fits.gui.main_window.emergency_stop import terminate_application; terminate_application()'],
                               timeout=15).returncode

    monkeypatch.setattr(launcher, 'launch_gui', quit_gui)
    assert launcher.startup(updater, [], skip_check=True) == 0
    assert not updater.pending.exists()
