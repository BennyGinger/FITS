from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from fits.environment.constant import Mode
from fits.environment.context import ExecutionContext


CURRENT_CTX: ContextVar[ExecutionContext] = ContextVar("CURRENT_CTX")

def get_ctx() -> ExecutionContext:
    try:
        return CURRENT_CTX.get()
    except LookupError:
        raise RuntimeError("ExecutionContext is not set. Call with use_ctx(ctx): ...")

@contextmanager
def use_ctx(ctx: ExecutionContext) -> Iterator[None]:
    token = CURRENT_CTX.set(ctx)
    try:
        yield
    finally:
        CURRENT_CTX.reset(token)
        
def detect_notebook() -> bool:
    try:
        from IPython.core.getipython import get_ipython
        ip = get_ipython()
        return ip is not None and ip.__class__.__name__ == "ZMQInteractiveShell"
    except Exception:
        return False
    
def detect_qt_gui_running() -> bool:
    try:
        from PySide6.QtWidgets import QApplication
        return QApplication.instance() is not None
    except Exception:
        return False
    
def detect_mode() -> Mode:
    # Priority matters
    if detect_qt_gui_running():
        return "gui"
    if detect_notebook():
        return "notebook"
    return "cli"