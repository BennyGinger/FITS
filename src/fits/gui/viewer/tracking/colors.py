"""Stable tracking colours shared by the viewer and ImageJ export."""

import colorsys


def track_rgb(track_id: int) -> tuple[int, int, int]:
    """
    Generate a stable, distinct RGB colour for a track identifier.
    """
    hue = (track_id * 0.61803398875) % 1.0
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
    return int(red * 255), int(green * 255), int(blue * 255)


def hex_rgb(color: str) -> tuple[int, int, int]:
    """
    Convert a six-digit hexadecimal colour string to RGB.
    """
    value = color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid RGB color {color!r}.")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
