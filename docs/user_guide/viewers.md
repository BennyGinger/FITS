# Image and mask viewers

[User guide](README.md)

For a simple inventory of each tool's controls, see
[Preview and editing GUIs](gui_tools.md).

For tool-specific settings, see [segmentation](segmentation.md),
[preprocessing](preprocessing.md), [tracking](tracking.md), and
[reference/ROI drawing](reference_and_roi_masks.md). Developer details about
storage and caches are in [runtime and viewer internals](../dev/runtime_and_viewer_internals.md).

## Inspecting artifact metadata in ImageJ/Fiji

FITS-generated **TIFF images and masks carry metadata inside the file**. Along
with image dimensions, channel labels, calibration, and timing where available,
FITS writes a readable summary of its processing metadata into the TIFF's
ImageJ **Info** field. You can inspect that summary without opening FITS or
writing Python code.

This applies to converted and preprocessed TIFF images, segmentation/tracking
masks, and saved REF/ROI masks. The available fields depend on the artifact,
its processing history, and the FITS version that saved it.

### Open the metadata summary

1. In ImageJ or Fiji, choose **File → Open…** and open the FITS `.tif` file you
   want to inspect.
2. Select that image window, then choose **Image → Show Info…**.
3. Scroll through the information window to the FITS sections. The summary is
   arranged into named sections and `key = value` entries.

ImageJ documents the command in its
[Image menu reference](https://imagej.net/ij/docs/guide/146-28.html).
Viewing this information does not change the saved artifact.

### What information can I find?

| Section or field | What it describes |
| --- | --- |
| `fits_io` | Artifact information recorded by the I/O layer. |
| `artifact_type` | The output's role, such as a raw/processed image or a mask. |
| `axes`, `channel_labels` | Stored dimensions and image/mask channel names. |
| `created_by`, `version` | Producer information when supplied. |
| `created_at` | Artifact revision timestamp when available. |
| `derived_from` | Recorded input references, including their paths/revisions where available. |
| `pipeline_meta` | FITS-level information supplied by the pipeline. |
| `steps` | Recorded processing steps, software information, and their settings. |
| `registration_revisions` | Identifiers for the registration runs associated with the artifact's image geometry. |
| `geometry_dependency`, `geometry_review` | Geometry information used to check or accept REF/ROI alignment, when present. |

For example, an artifact's `steps` sections can show the registration algorithm,
background-subtraction settings, or segmentation model/settings carried through
its history. For masks, some recorded settings describe the source image used
to generate or draw them. Fields can be absent in older files or when the
corresponding processing step has not occurred.

### Readable summary versus current FITS metadata

The ImageJ summary is generated when the TIFF is written. FITS also keeps a
structured metadata record in a private TIFF tag, which its processing and
file-management checks read directly.

**A metadata-only maintenance operation can update that structured record
without regenerating the ImageJ Info text.** The readable summary can therefore
reflect the earlier write. Use the current FITS status, conflict checks, and
**Manage files…** when checking whether results or REF/ROI geometry are up to date.

### What about measurement tables?

Parquet (`.parquet`) artifacts use file-level Parquet metadata rather than an
ImageJ Info field. They are not inspected through ImageJ. Open their measurement
columns with Tad, Data Wrangler, or Python; see
[Understanding the output tables](output_tables.md) for the distinction between
dataframe columns and file-level provenance. The JSON experiment state and
TOML settings files are also separate from a TIFF's ImageJ summary.

## Opening images and masks

**Image / Mask Viewer** opens raw `.nd2`, `.tif` and `.tiff` inputs before
conversion, as well as current intermediates, canonical compacted images
and masks, supported older FITS files, and REF/ROI masks. Trajectories and track-length
filtering appear for tracked masks. Segmentation and branch masks offer image/mask
display without tracking-only tools. Earlier-version files cannot be edited.
The existing `fits-trackviewer` command also opens these supported files.

Raw images are read one plane at a time, with Frame, Channel and Z navigation.
A **Series** selector appears for acquisitions with multiple positions/series.
Raw ND2 channels use their stored NIS display colors; raw TIFF channels use
colors from ImageJ LUTs. Unavailable colors fall back to grayscale; the
Grayscale button temporarily overrides the stored color display.
FITS artifacts continue to use label-based colors. Raw browsing does not enable
mask editing or saving, and the other tuners/editors still require FITS artifacts.

## Drawing, selection, and keyboard shortcuts

Reference/ROI drawing offers **Brush** strokes and **Freehand polygon** fills.
Shift-click selects the connected mask region under the cursor; drag it to move
it, or use Shift-drag directly. Movement stays within the image and supports
Ctrl+Z. ROI movement retains local threshold states through manual overrides.
**Clear current** clears the displayed plane; **Clear all** clears every T/Z
plane of the selected mask channel in the session. Existing saved masks stay
unchanged unless you explicitly save a replacement. Clearing records empty
planes without reading or rewriting their pixels; reference Undo retains the
previous plane through storage references. Tracking deletion likewise defers
label removal until display/save and updates cached centroids directly.
Brush sizes up to 1001 pixels are available in REF/ROI and tracking.
Both settings panels keep
Undo, Clear current, and Clear all together in an untitled section below the
title and description, with Ctrl+Z, Ctrl+D,
and Ctrl+Shift+D shortcuts respectively. Every viewer Info button shows the
shared searchable shortcut table, filtered to the current viewer, with function
and mode/condition columns. GUI applicability stays hidden. Both tracking modes
have a Selection panel above Display settings, with the selected IDs, Clear
selection, and cell-ID entry. The viewer accepts comma-separated IDs and an
unlimited number of selected cells; Ctrl+click and text entry stay synchronised.
The tracking editor keeps its single-ID input and maximum of two selected tracks.
Press Enter or Select to apply IDs; unavailable or filtered-out IDs leave the
current selection unchanged. In the tracking viewer, Ctrl+left-click toggles a
cell, while Ctrl+left-drag selects all current-frame centroids inside a
temporary rectangle. In the editor, Ctrl+left-click selects a cell and
Ctrl+left-drag pans. Ctrl+scroll zooms in both.
To inspect the complete shortcut catalog, including its GUI applicability, run
`.venv/bin/python -m fits.gui.viewer.common.inspect_shortcuts` from the repository.
Info dialogs size their wrapped columns and rows to the current screen. REF/ROI
save preparation and tracking preparation/saving use the same white loading
overlay, with a status message; it clears on completion or failure.

## Exporting overlays and cropping

In the read-only tracking viewer, **Save current display** writes a new
`fits_track_overlay[_filtered][_label].tif`: all channels, Z planes, and frames
from the associated image artifact, with their original pixel values, plus an embedded ImageJ
overlay. The current mask channel, Z plane, filtering, path/ID selection,
colours, and mask opacity determine the annotations across time. Annotations
appear over any raw channel at the selected Z plane. The source files remain
untouched; the raw image is required even when its display is switched off.
This export is uncompressed because ImageJ's native compressed-stack opener
can omit embedded overlays, so it may be considerably larger than the source.
Open it in ImageJ/Fiji with **File → Open** and toggle annotations with
**Image → Overlay → Hide Overlay / Show Overlay**. **To ROI Manager** exposes
the separately named masks, paths, centroid markers, and IDs. Save as TIFF to
retain the overlay.

The viewer's **Crop** panel sits below Track filtering. Turn on **Enable crop**
and click **Crop** to fit a rectangle around every selected cell's complete
masks across the recording, with 5% padding on each side. Fitting runs in the
background. You can also draw a rectangle with a left drag, with or without
Ctrl; cells whose current-frame centroids are inside it become selected. The
rectangle stays until you change or disable crop mode. Drag inside it to move
it, or drag an edge/corner to resize it. Clicking Crop again fits the rectangle
around the selected cells across time. Width and Height are
editable pixel dimensions. Manual rectangles and adjustments receive no added
padding. The rectangle colour is only a display aid.
**Preview** zooms to the rectangle; unchecking Preview or pressing Home shows
the full image. **Save current display** uses the current rectangle whenever
crop mode is enabled, in either view, and adds `_cropped` to the filename.
Turning crop mode off saves the full image. All raw channels, frames, and Z
planes use the same XY crop, with the embedded overlay clipped and shifted to
match. `fits_io` preserves metadata/calibration and records the source shape,
pixel bounds, and offsets in `spatial_crops` metadata.
