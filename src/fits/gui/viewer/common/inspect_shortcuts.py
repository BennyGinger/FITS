"""Open the complete shortcut catalog for inspection from the terminal."""

from PySide6.QtWidgets import QApplication

from fits.gui.viewer.common.information_dialog import ViewerInformationDialog


if __name__ == "__main__":
    application = QApplication.instance() or QApplication([])
    dialog = ViewerInformationDialog(title="All viewer shortcuts", version="development")
    dialog.exec()
