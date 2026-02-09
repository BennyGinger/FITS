import pytest
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment import runtime
from fits.environment.context import ExecutionContext


def test_get_ctx_raises_when_unset() -> None:
    with pytest.raises(RuntimeError, match="ExecutionContext is not set"):
        get_ctx()

def test_use_ctx_sets_and_resets_context() -> None:
    ctx = ExecutionContext(user_name='some_user')  
    with use_ctx(ctx):
        assert get_ctx() is ctx
    with pytest.raises(RuntimeError):
        get_ctx()

def test_use_ctx_is_reentrant_and_restores_previous() -> None:
    ctx1 = ExecutionContext(user_name='user1')
    ctx2 = ExecutionContext(user_name='user2')

    with use_ctx(ctx1):
        assert get_ctx() is ctx1
        with use_ctx(ctx2):
            assert get_ctx() is ctx2
        assert get_ctx() is ctx1

def test_detect_mode_prefers_gui_over_notebook(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "detect_qt_gui_running", lambda: True)
    monkeypatch.setattr(runtime, "detect_notebook", lambda: True)
    assert runtime.detect_mode() == "gui"

def test_detect_mode_notebook_when_no_gui(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "detect_qt_gui_running", lambda: False)
    monkeypatch.setattr(runtime, "detect_notebook", lambda: True)
    assert runtime.detect_mode() == "notebook"

def test_detect_mode_cli_fallback(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "detect_qt_gui_running", lambda: False)
    monkeypatch.setattr(runtime, "detect_notebook", lambda: False)
    assert runtime.detect_mode() == "cli"