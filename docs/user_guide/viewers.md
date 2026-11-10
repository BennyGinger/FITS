# Image and mask viewers

[User guide](README.md)

For a simple inventory of each tool's controls, see
[Preview and editing GUIs](gui_tools.md).

For tool-specific settings, see [segmentation](segmentation.md),
[preprocessing](preprocessing.md), [tracking](tracking.md), and
[reference/ROI drawing](reference_and_roi_masks.md). Developer details about
storage and caches are in [runtime and viewer internals](../dev/runtime_and_viewer_internals.md).

## Experiment browser

Tuners, File Viewer and Track Editor show the selected experiment directly in
the browser. Its parent folders expand automatically and the complete ancestry
is highlighted in blue, following each row's indentation. The browser starts
taller; drag the horizontal divider to adjust its height. There is no wrapping selected-path label below the
tree; that space is used for additional browser rows. The highlighted parents
are visual context, not additional selected experiments.

## Inspecting artifact metadata in ImageJ/Fiji

FIScH-generated **TIFF images and masks carry metadata inside the file**. Along
with image dimensions, channel labels, calibration, and timing where available,
FIScH writes a readable summary of its processing metadata into the TIFF's
ImageJ **Info** field. You can inspect that summary without opening FIScH or
writing Python code.

This applies to converted and preprocessed TIFF images, segmentation/tracking
masks, and saved REF/ROI masks. The available fields depend on the artifact,
its processing history, and the FIScH version that saved it.

### Open the metadata summary

1. In ImageJ or Fiji, choose **File → Open…** and open the FIScH `.tif` file you
   want to inspect.
2. Select that image window, then choose **Image → Show Info…**.
3. Scroll through the information window to the FIScH sections. The summary is
   arranged into named sections and `key = value` entries.

ImageJ documents the command in its
[Image menu reference](https://imagej.net/ij/docs/guide/146-28.html).
Viewing this information does not change the saved artifact.

### What information can I find?

| Section or field | What it describes |
| --- | --- |
| `artifact` | Artifact information recorded by the I/O layer. |
| `artifact_type` | The output's role, such as a raw/processed image or a mask. |
| `axes`, `channel_labels` | Stored dimensions and image/mask channel names. |
| `created_by`, `version` | Producer information when supplied. |
| `created_at` | Artifact revision timestamp when available. |
| `derived_from` | Recorded input references, including their paths/revisions where available. |
| `pipeline_meta` | FIScH-level information supplied by the pipeline. |
| `steps` | Recorded processing steps, software information, and their settings. |
| `registration_revisions` | Identifiers for the registration runs associated with the artifact's image geometry. |
| `geometry_dependency`, `geometry_review` | Geometry information used to check or accept REF/ROI alignment, when present. |

For example, an artifact's `steps` sections can show the registration algorithm,
background-subtraction settings, or segmentation model/settings carried through
its history. For masks, some recorded settings describe the source image used
to generate or draw them. Fields can be absent in older files or when the
corresponding processing step has not occurred.

### Readable summary versus current FIScH metadata

The ImageJ summary is generated when the TIFF is written. FIScH also keeps a
structured metadata record in a private TIFF tag, which its processing and
file-management checks read directly.

**A metadata-only maintenance operation can update that structured record
without regenerating the ImageJ Info text.** The readable summary can therefore
reflect the earlier write. Use the current FIScH status, conflict checks, and
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
and masks, supported older FIScH files, and REF/ROI masks. Trajectories and track-length
filtering appear for tracked masks. Segmentation and branch masks offer image/mask
display without tracking-only tools. Earlier-version files cannot be edited.
The existing `fisch-trackviewer` command also opens these supported files.

Raw images are read one plane at a time, with Frame, Channel and Z navigation.
A **Series** selector appears for acquisitions with multiple positions/series.
Raw ND2 channels use their stored NIS display colors; raw TIFF channels use
colors from ImageJ LUTs. Unavailable colors fall back to grayscale; the
Grayscale button temporarily overrides the stored color display.
FIScH artifacts continue to use label-based colors. Raw browsing does not enable
mask editing or saving, and the other tuners/editors still require FIScH artifacts.

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
cell. A plain left drag draws a measurement rectangle and selects cells whose
current-frame centroids lie inside it. Ctrl+left-drag pans and Ctrl+scroll zooms
in both the viewer and editor.
To inspect the complete shortcut catalog, including its GUI applicability, run
`.venv/bin/python -m fisch.gui.viewer.common.inspect_shortcuts` from the repository.
Info dialogs size their wrapped columns and rows to the current screen. REF/ROI
save preparation and tracking preparation/saving use the same white loading
overlay, with a status message; it clears on completion or failure.

## Exporting overlays and cropping

In the read-only tracking viewer, **Save current display** writes a new
`proc_track_overlay[_filtered][_label].tif`: all channels, Z planes, and frames
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

The viewer's **Draw** section sits above **Crop**. Rectangle is the default:
left-drag empty space to draw, drag inside the outline to move it, and drag its
edges or corners to resize it. Choose Ellipse for an elliptical area, or Polygon
and click vertices, double-clicking the last vertex to finish. Polygon vertices
can be dragged individually. A single click outside clears the selection; a new
drag replaces it. The shape remains visible independently of crop mode. Shape
colour is a display aid and is not exported.

The **Full range** (left) and **Auto-scale** (right) buttons match **Show profile**
in font and size. They share one top-aligned row immediately above the LUT graph.
The controls, graph and Intensities box form a fixed 560 × 125 px block, with padding around the intensity border.
Resizing the image pane or window does not stretch the LUT or the save/action
panels. The footer sits outside the image splitter, so changing the image
height leaves the controls at the same positions. Extra window space goes to
the image display. Intensities fills
the height below Show profile, aligned with the graph at its top and bottom. The bordered **Intensities** box aligns with its bottom and normally shows
the hovered pixel. With a shape selected it shows the signed source mean,
labelled **Mean**, over the actual shape interior. **Show profile**, above the
Intensities box, opens a live mean-intensity curve for the selected channel. Its x-axis
dropdown selects Time (seconds when calibrated, otherwise frame) or Z plane; unavailable dimensions are disabled.
Time holds the current Z plane fixed, and Z holds the current frame fixed. Moving
or reshaping the area refreshes the profile in the background. The shape stays
at fixed image coordinates rather than following a tracked cell. Closing the
plot stops profile processing. Prepared planes remain in a temporary mapped
cache for fast area changes and reopening; changing the source/axis context or
closing the viewer releases those files. Plot opening starts immediately, while
selection changes are throttled briefly to keep interaction responsive.

In the profile window, **Home** at the upper left fits and centres all curves.
Double-click the X or Y axis to enter its minimum and maximum. Each axis has an
**R** control: above Y and at the right end of X. R restores that axis's automatic
range without changing the other axis; Home resets both. Opening or reopening
the profile also fits and centres both axes automatically. Manual ranges remain
in effect during live curve updates. Switching Time/Z resets the X range for
the new dimension. Curve labels appear in one centred row below the Time/Z
selector, outside the graph in the gray footer.

Turn on **Enable crop** and click **Crop** to fit a rectangle around every
selected cell's complete trajectory, with 5% padding on each side. This replaces
the shared drawing selection. Width and Height remain editable; numeric changes
produce a rectangular selection. For ellipses and polygons, export uses the
shape's bounding rectangle while intensity measurements use its actual interior.
Manual selections receive no added padding.
**Preview** zooms to the rectangle; unchecking Preview or pressing Home shows
the full image. **Save current display** uses the current rectangle whenever
crop mode is enabled, in either view, and adds `_cropped` to the filename.
Turning crop mode off saves the full image. All raw channels, frames, and Z
planes use the same XY crop, with the embedded overlay clipped and shifted to
match. `scope_io` preserves metadata/calibration and records the source shape,
pixel bounds, and offsets in `spatial_crops` metadata.
