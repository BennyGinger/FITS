"""Immutable image-coordinate selections shared by measurement and profiles."""

from dataclasses import dataclass
from math import ceil, floor
from typing import Any

import numpy as np
from numpy.typing import NDArray
from skimage.measure import points_in_poly

from fisch.interaction.crop import CropBounds


@dataclass(frozen=True)
class AreaSelection:
    """
    Describe a rectangle, ellipse or polygon independently of Qt graphics.
    """

    kind: str
    points: tuple[tuple[float, float], ...]

    def bounds(self, shape: tuple[int, int]) -> CropBounds:
        """
        Return clipped integer bounds with exclusive right and bottom edges.
        """
        x, y = zip(*self.points)
        height, width = shape
        return (max(0, min(width, floor(min(x)))), max(0, min(height, floor(min(y)))),
                max(0, min(width, ceil(max(x)))), max(0, min(height, ceil(max(y)))))

    def pixels(self, shape: tuple[int, int]) -> tuple[CropBounds, NDArray[np.bool_]]:
        """
        Select pixel centres inside the shape using only its bounding rectangle.
        """
        bounds = self.bounds(shape)
        left, top, right, bottom = bounds
        if self.kind == "Rectangle":
            return bounds, np.ones((bottom - top, right - left), dtype=bool)
        yy, xx = np.mgrid[top:bottom, left:right].astype(float) + 0.5
        if self.kind == "Ellipse":
            x, y = zip(*self.points)
            rx, ry = (max(x) - min(x)) / 2, (max(y) - min(y)) / 2
            mask = (((xx - (max(x) + min(x)) / 2) / max(rx, 1e-9)) ** 2
                    + ((yy - (max(y) + min(y)) / 2) / max(ry, 1e-9)) ** 2 <= 1)
        elif self.kind == "Polygon":
            mask = points_in_poly(np.column_stack((xx.ravel(), yy.ravel())), np.asarray(self.points)).reshape(xx.shape)
        else:
            mask = np.ones(xx.shape, dtype=bool)
        return bounds, mask

    def mean(self, image: NDArray[Any], *, pixels: tuple[CropBounds, NDArray[np.bool_]] | None = None) -> float:
        """
        Measure signed, unscaled source intensities inside the selection.
        """
        if self.kind == "Rectangle":
            left, top, right, bottom = pixels[0] if pixels is not None else self.bounds((image.shape[0], image.shape[1]))
            values = image[top:bottom, left:right]
        else:
            (left, top, right, bottom), mask = pixels if pixels is not None else self.pixels((image.shape[0], image.shape[1]))
            values = image[top:bottom, left:right][mask]
        return float(np.mean(values, dtype=np.float64)) if values.size else float("nan")
