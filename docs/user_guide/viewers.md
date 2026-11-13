# Image and mask viewers

[Guide home](README.md)

Related: [File Viewer](tools/tracking_viewer.md) · [Viewer controls](tools/viewer_controls.md) · [Tracking editor](tools/tracking_editor.md)

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

See [File Viewer](tools/tracking_viewer.md).

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

See [File Viewer export and crop controls](tools/tracking_viewer.md).
