"""A display-only, image-pixel-sized reference for Cellpose's diameter."""
import math

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsEllipseItem


class DiameterReference(QGraphicsEllipseItem):
    def __init__(self, view_box, image_item):
        super().__init__()
        self.view_box = view_box
        self.image_item = image_item
        self.diameter = 0.0
        self.setBrush(QColor(255, 80, 80, 180))
        pen = pg.mkPen("white", width=1)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(200)
        view_box.addItem(self, ignoreBounds=True)
        view_box.sigRangeChanged.connect(self.refresh)
        self.hide()

    def set_diameter(self, diameter: float):
        self.diameter = float(diameter)
        self.refresh()

    def refresh(self, *args):
        diameter = self.diameter
        if (self.image_item.image is None or not math.isfinite(diameter)
                or diameter <= 0):
            self.hide()
            return
        visible = self.view_box.viewRect().intersected(self.image_item.boundingRect())
        if visible.isEmpty():
            self.hide()
            return
        # Image Y increases downwards. Geometry is in image pixels, so the disk
        # zooms with the cells while remaining near the visible lower-left edge.
        margin = min(5.0, visible.width() * .02, visible.height() * .02)
        self.setRect(0, 0, diameter, diameter)
        self.setPos(visible.left() + margin, visible.bottom() - diameter - margin)
        self.setToolTip(f"Selected cell diameter: {diameter:g} image pixels")
        self.show()
