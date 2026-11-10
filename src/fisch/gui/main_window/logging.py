"""Qt bridge for records emitted by the pipeline logger."""

import logging

from PySide6.QtCore import QObject, Signal


class LogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """
    Forward formatted records to the Qt event loop.
    """

    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.message.emit(self.format(record))
        except Exception:
            self.handleError(record)
