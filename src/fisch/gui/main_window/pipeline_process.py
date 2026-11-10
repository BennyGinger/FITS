"""Run processing in an isolated process and exchange existing workflow messages."""

from __future__ import annotations

from collections.abc import Callable
import logging
from multiprocessing.connection import Connection
import os
from pathlib import Path
from queue import Empty
from threading import Event, Lock, Thread
import traceback
from typing import Any

from fisch.channel_labels.lock import run_write_guard
from fisch.gui.main_window.emergency_stop import terminate_application
from fisch.pipeline import start_pipeline
from fisch.settings.loader import load_settings
from fisch.workflows.runtime.errors import PipelineCancelled
from fisch.workflows.runtime.interactive import PipelineInteraction
from fisch.workflows.runtime.progress import RunProgress


class _Messages:
    """
    Serialize concurrent log, progress and interaction events onto one pipe.
    """

    def __init__(self, connection: Connection) -> None:
        """
        Share the process connection across workflow threads.
        """
        self.connection = connection
        self._lock = Lock()

    def send(self, name: str, payload: Any = None) -> None:
        """
        Publish one complete event without interleaving writes from other threads.
        """
        with self._lock:
            self.connection.send((name, payload))


class _ProcessLogHandler(logging.Handler):
    """
    Send log records to the parent without attempting to pickle tracebacks.
    """

    def __init__(self, messages: _Messages) -> None:
        """
        Forward child logging through the shared event channel.
        """
        super().__init__()
        self.messages = messages

    def emit(self, record: logging.LogRecord) -> None:
        """
        Preserve severity, logger and timestamps while flattening exception details.
        """
        payload = dict(record.__dict__)
        payload['msg'], payload['args'] = record.getMessage(), ()
        payload['exc_text'] = logging.Formatter().formatException(record.exc_info) if record.exc_info else record.exc_text
        payload['exc_info'] = None
        self.messages.send('log', payload)


def _receive_commands(connection: Connection, interaction: PipelineInteraction) -> None:
    """
    Deliver GUI decisions and drawing outcomes to the existing interaction queues.
    """
    try:
        while True:
            name, payload = connection.recv()
            if name == 'cancel':
                interaction.cancel()
            elif name == 'mask':
                interaction.resolve_mask(payload)
            elif name == 'masks_finished':
                interaction.finish_mask_collection()
            elif name == 'tracking':
                interaction.resolve_track_edit(payload)
            elif name == 'decision':
                interaction.decisions.put(payload)
    except (EOFError, OSError):
        # A vanished supervisor must not leave CPU/GPU workers processing unattended.
        terminate_application()


def _publish_progress(messages: _Messages, progress: RunProgress, stopped: Event) -> None:
    """
    Send inexpensive progress snapshots while processing or native inference is active.
    """
    while not stopped.wait(0.15):
        messages.send('progress', (progress.snapshot(), progress.display.snapshot()))


def run_pipeline_process(connection: Connection,
                         settings_path: Path,
                         options: dict[str, Any],
                         runner: Callable[..., Any] | None = None,
                         ) -> None:
    """
    Execute a pipeline in its own process group without importing a Qt application.
    """
    if os.name == 'posix':
        os.setsid()
    messages = _Messages(connection)
    messages.send('started', os.getpid())
    interaction = PipelineInteraction(lambda request: messages.send('mask_request', request),
                                       lambda: messages.send('masks_complete'),
                                       lambda count: messages.send('mask_count', count),
                                       lambda request: messages.send('tracking_request', request),
                                       decision_request=lambda report: messages.send('decision_request', report))
    progress = RunProgress()
    stopped = Event()
    Thread(target=_receive_commands, args=(connection, interaction), daemon=True).start()
    publisher = Thread(target=_publish_progress, args=(messages, progress, stopped), daemon=True)
    publisher.start()
    outcome: tuple[str, Any] = ('finished', None)
    try:
        root = Path(load_settings(settings_path)['run_dir']).expanduser().resolve()
        with run_write_guard(root):
            (runner or start_pipeline)(settings_path=settings_path,
                                       console_handler=_ProcessLogHandler(messages),
                                       interaction=interaction,
                                       run_progress=progress,
                                       terminal_progress=False,
                                       **options)
    except PipelineCancelled:
        outcome = ('cancelled', None)
    except BaseException as error:
        from fisch.gui.main_window.pipeline_worker import user_error_message
        outcome = ('failed', (user_error_message(error), traceback.format_exc()))
    finally:
        stopped.set()
        publisher.join()
    messages.send('progress', (progress.snapshot(), progress.display.snapshot()))
    messages.send(*outcome)
    # The daemon command reader exits with the process; close after the final event.


def send_interaction_commands(connection: Connection, interaction: PipelineInteraction) -> None:
    """
    Drain completed GUI interactions without blocking the supervising worker thread.
    """
    for name, queue in (('mask', interaction.mask_outcomes), ('tracking', interaction.track_edit_outcomes),
                        ('decision', interaction.decisions)):
        while True:
            try:
                connection.send((name, queue.get_nowait()))
            except Empty:
                break
