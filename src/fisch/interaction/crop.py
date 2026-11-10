"""Crop bounds in full-image coordinates; right and bottom edges are exclusive."""

CropBounds = tuple[int, int, int, int]


def validate_crop(crop: CropBounds | None, width: int, height: int) -> None:
    """Reject empty, noninteger or out-of-image fitting rectangles."""
    if crop is None:
        return
    if len(crop) != 4 or any(isinstance(value, bool) or not isinstance(value, int) for value in crop):
        raise ValueError("Crop bounds must contain four integer pixel coordinates.")
    x0, y0, x1, y1 = crop
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("Crop rectangle must lie inside the image and have positive width and height.")
