"""Discover Cellpose options once in a worker shared by the GUI."""

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication

from fits.gui.segmentation_models.options import CellposeModelOptions, installed_model_options


class _DiscoveryThread(QThread):
    """
    Import the backend and read model choices without accessing widgets.
    """

    def __init__(self, discover: Callable[[], CellposeModelOptions], parent: QObject) -> None:
        """
        Retain discovery and its result until the GUI receives completion.
        """
        super().__init__(parent)
        self.discover = discover
        self.options: CellposeModelOptions | None = None
        self.error = ''

    def run(self) -> None:
        """
        Capture discovery errors for presentation on the GUI thread.
        """
        try:
            self.options = self.discover()
        except Exception as error:
            self.error = str(error)


class ModelOptionsLoader(QObject):
    """
    Own one background task and publish its result on the GUI thread.
    """

    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject, discover: Callable[[], CellposeModelOptions] = installed_model_options) -> None:
        """
        Prepare discovery without doing work during window construction.
        """
        super().__init__(parent)
        self.options: CellposeModelOptions | None = None
        self.error = ''
        self._started = False
        self._thread = _DiscoveryThread(discover, self)
        self._thread.finished.connect(self._finished)

    def start(self) -> None:
        """
        Start discovery once, reusing the same task for all consumers.
        """
        if not self._started:
            self._started = True
            self._thread.start()

    def wait(self) -> None:
        """
        Finish outstanding imports before Qt destroys the application and its threads.
        """
        self._thread.wait()

    def _finished(self) -> None:
        """
        Publish successful choices or a failure without changing user settings.
        """
        self.options = self._thread.options
        self.error = self._thread.error
        if self.options is not None:
            self.ready.emit(self.options)
        else:
            self.failed.emit(self.error)


def model_options_loader() -> ModelOptionsLoader:
    """
    Share application-owned discovery, scheduled after the initial window can paint.
    """
    app = QApplication.instance()
    if app is None:
        raise RuntimeError('Create the Qt application before requesting model choices.')
    loader = app.findChild(ModelOptionsLoader, 'fits-cellpose-model-options')
    if loader is None:
        loader = ModelOptionsLoader(app)
        loader.setObjectName('fits-cellpose-model-options')
        app.aboutToQuit.connect(loader.wait)
        QTimer.singleShot(100, loader.start)
    return loader
