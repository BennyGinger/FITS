"""PySide6 desktop interface for FIScH."""

from __future__ import annotations

import os

# Dependencies may import another Qt binding before a viewer is opened. Every
# FIScH widget uses PySide6, so pyqtgraph must use the same binding as well.
os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"

"""Qt user interface for FIScH."""
