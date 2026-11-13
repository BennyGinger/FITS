"""One shortcut catalog, filtered by the active tool and editing mode."""

from collections.abc import Sequence

HelpRow = tuple[str, str, str, str]

COMMON_HELP: tuple[HelpRow, ...] = (
    ("S", "Save / apply current work", "REF / ROI / SegTune / RegTune / BGTune / Tracking",
     "Current mask, settings, or ready editing preview"),
    ("Ctrl+Z", "Undo the latest edit or preview", "REF / ROI / Tracking", "Editing"),
    ("X", "Toggle mask overlay", "All viewers", "All modes"),
    ("← / → or A / D", "Previous / next frame", "All viewers", "All modes"),
    ("↑ / ↓ or W / Z", "Next / previous Z plane", "All viewers", "All modes"),
    ("C", "Next active image channel", "All viewers", "All modes"),
    ("Ctrl+left click (hold), drag", "Pan image", "All viewers", "All modes"),
    ("Ctrl+scroll", "Zoom image",
     "All viewers", "All modes"),
)

EDITING_HELP: tuple[HelpRow, ...] = (
    ("Ctrl+D", "Remove the current mask", "REF / ROI / Tracking",
     "Editing; current plane (REF/ROI) or selected track's current mask (Tracking)"),
    ("Ctrl+Shift+D", "Remove all masks in the selection", "REF / ROI / Tracking",
     "Editing; selected channel (REF/ROI) or selected track (Tracking), across frames"),
    ("Left click / drag", "Draw / add", "REF / ROI / Tracking",
     "Editing; REF/ROI: Replace/Edit; Tracking: Add/Edit or Split Mask"),
    ("Right click / drag", "Erase / remove", "REF / ROI / Tracking",
     "Editing; REF/ROI: Replace/Edit; Tracking: Add/Edit"),
)

MASK_HELP: tuple[HelpRow, ...] = (
    ("Shift+left click (hold), drag", "Select and move the connected mask region under the cursor",
     "REF / ROI", "Drawing"),
)

SEGMENTATION_HELP: tuple[HelpRow, ...] = (
    ("R", "Run preview", "SegTune / RegTune", "Tuning; RegTune can cancel an active preview"),
)

PREPROCESSING_HELP: tuple[HelpRow, ...] = (
    ("V", "Toggle original / preprocessed view", "RegTune / BGTune", "Keep the same frame and Z plane"),
)

REGISTRATION_HELP = (*SEGMENTATION_HELP, *PREPROCESSING_HELP)

BACKGROUND_HELP: tuple[HelpRow, ...] = (
    *PREPROCESSING_HELP,
    ("R", "Run preview", "BGTune", "Selected frame, channel and Z plane only"),
    ("Left click / drag", "Draw, move or resize measurement area", "BGTune", "Rectangle is the default; click outside to clear"),
)

TRACKING_HELP: tuple[HelpRow, ...] = (
    ("Ctrl+left click mask or centroid", "Select / unselect track", "Tracking", "Edit or selection enabled"),
    ("Left click / drag", "Draw, move or resize measurement area", "Tracking", "Viewer only; rectangle also selects masks"),
)

# Mode details preserve the differences behind the shared gestures. Full-catalog
# inspection uses the general conditions above; normal dialogs show local ones.
HELP_CONDITIONS: dict[str, dict[str, str]] = {
    "REF / ROI": {
        "S": "Current mask",
        "Ctrl+Z": "Current plane",
        "Ctrl+D": "Current plane; session only",
        "Ctrl+Shift+D": "Selected channel; all frames and Z planes; session only",
        "Left click / drag": "Replace / Edit; selected drawing tool",
        "Right click / drag": "Replace / Edit; selected drawing tool",
    },
    "SegTune": {"S": "Current settings", "R": "Tuning"},
    "BGTune": {"S": "Save current settings and stay open; preview optional",
               "C": "Included channels only; excluded channels remain selectable in the channel menu",
               "V": "Original / background-subtracted image; same LUT and intensity limits"},
    "RegTune": {"S": "Current tab; preview optional",
                "C": "Time: all channels. Channel: included comparison channels; reference stays fixed. "
                     "Excluded channels remain selectable in the channel menu.",
                "V": "Time: original / registered image. Channel: original / registered alignment "
                     "for the same reference and comparison channel."},
    "Tracking": {
        "S": "Split / Add/Edit; ready preview (applies in session)",
        "Ctrl+D": "Edit; selected track's mask in the current frame",
        "Ctrl+Shift+D": "Edit; selected track; all frames in the current channel/Z plane",
        "Left click / drag": (
            "Edit → Add/Edit: click predicts/adds, drag brushes.\n"
            "Edit → Split Mask: click/drag marks the division inside the selected mask."),
        "Right click / drag": "Edit → Add/Edit: click predicts/removes, drag erases",
    },
}

# One catalog serves every viewer; GUI applicability is internal filter metadata.
VIEWER_HELP = (*COMMON_HELP, *EDITING_HELP, *MASK_HELP, *SEGMENTATION_HELP, *BACKGROUND_HELP, *TRACKING_HELP)



def relevant_shortcuts(rows: Sequence[HelpRow], gui: str | None, editing_enabled: bool, selection_enabled: bool) -> list[HelpRow]:
    """
    Select catalog entries available in the current interface.
    """
    if gui is None:
        return list(dict.fromkeys(rows))
    if gui not in {"REF", "ROI", "REF / ROI", "SegTune", "RegTune", "BGTune", "Tracking"}:
        return []
    active = set(gui.split(" / "))
    result = [row for row in rows if row[2] == "All viewers" or active.intersection(row[2].split(" / "))]
    if gui == "Tracking":
        result = [row for row in result
                  if (editing_enabled or (not row[3].startswith("Edit") and row[0] not in {"S", "Ctrl+Z"}))
                  or (row[0] == "Ctrl+left click mask or centroid" and selection_enabled)]
        if editing_enabled:
            result = [row for row in result if row[3] != "Viewer only; rectangle also selects masks"]
    if gui in ("BGTune", "RegTune"):
        result = [row for row in result if row[0] != "X"]
    return list(dict.fromkeys(result))


def local_shortcuts(rows: Sequence[HelpRow], gui: str | None, editing_enabled: bool) -> list[HelpRow]:
    """
    Describe shared gestures using the current tool's terminology.
    """
    conditions = HELP_CONDITIONS.get("REF / ROI" if gui in {"REF", "ROI"} else gui or "", {})
    result = [(key, action, scope, conditions.get(key, mode)) for key, action, scope, mode in rows]
    if gui == "Tracking" and not editing_enabled:
        result = [(key, "Select cells in rectangle" if key == "Ctrl+left click (hold), drag" else action,
                   scope, mode) for key, action, scope, mode in result]
    return result
