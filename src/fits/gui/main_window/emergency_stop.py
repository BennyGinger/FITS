"""Immediately stop the desktop application and its processing descendants."""

from __future__ import annotations

import os
from typing import NoReturn

import psutil


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
    os._exit(1)
