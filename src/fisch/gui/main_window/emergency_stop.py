"""Immediately stop the desktop application and its processing descendants."""

from __future__ import annotations

import os
import signal
from typing import NoReturn

import psutil


def terminate_process_tree(pid: int, *, isolated_group: bool = False) -> None:
    """
    Stop an isolated pipeline and its descendants without terminating the GUI.
    """
    if pid == os.getpid():
        raise ValueError('Cannot terminate the supervising process.')
    try:
        process = psutil.Process(pid)
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        process, descendants = None, []
    try:
        for child in reversed(descendants):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        if os.name == 'posix' and (isolated_group or os.getpgid(pid) == pid):
            os.killpg(pid, signal.SIGKILL)
        elif process is not None:
            process.kill()
    except (psutil.NoSuchProcess, ProcessLookupError):
        pass


def terminate_application() -> NoReturn:
    """
    Kill descendant workers and exit without waiting for Python or Qt cleanup.
    """
    application = psutil.Process()
    for worker in reversed(application.children(recursive=True)):
        try:
            worker.kill()
        except psutil.NoSuchProcess:
            pass
    # An explicit user quit is not an application or installation failure.
    os._exit(0)
