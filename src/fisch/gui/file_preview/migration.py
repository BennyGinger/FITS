"""Switch migration reviews between relocation and optional full reconstruction."""

from PySide6.QtWidgets import QVBoxLayout, QWidget

from fisch.gui.file_preview.models import PreviewGroup
from fisch.gui.file_preview.portable import portable_groups
from fisch.gui.file_preview.processing import migration_rebuild_groups
from fisch.gui.file_preview.widget import FilePreviewWidget
from fisch.workflows.file_management.relocation import PortablePlan


class MigrationPreviewWidget(QWidget):
    """
    Keep the migration checkbox and displayed file actions synchronized.
    """

    def __init__(self, plan: PortablePlan, parent: QWidget | None = None) -> None:
        """
        Show the move/rename plan first, deferring optional reconstruction until requested.
        """
        super().__init__(parent)
        self._plan = plan
        self._moves = portable_groups(plan)
        self._rebuild: tuple[PreviewGroup, ...] | None = None
        self.diagram = FilePreviewWidget(self._moves, 'Migration only: move files and update metadata while preserving pixels and measurements.')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.diagram)
        self.setMinimumHeight(420)

    def show_rebuild(self, enabled: bool) -> None:
        """
        Preview full reconstruction when checked and restore relocation when unchecked.
        """
        if enabled:
            if self._rebuild is None:
                self._rebuild = migration_rebuild_groups(self._plan)
            self.diagram.set_groups(self._rebuild,
                                    'Migrate, then rebuild the full workflow from originals. '
                                    'This can take a long time and change results; current results are backed up first.')
        else:
            self.diagram.set_groups(self._moves, 'Migration only: move files and update metadata while preserving pixels and measurements.')
