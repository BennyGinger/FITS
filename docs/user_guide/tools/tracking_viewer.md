# File Viewer

[Guide home](../README.md)

Related: [Tracking overview](../tracking.md) · [Tracking editor](tracking_editor.md) · [Output tables](../output_tables.md) · [Settings](../settings/tracking.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

Open **File Viewer** in **Extra tools** to inspect raw ND2/TIFF images or saved
FIScH images and masks. The tracking controls below are available for tracked
masks; ordinary images and REF/ROI masks use the applicable image/mask controls.

- Choose the displayed image channel, mask channel, frame, and Z plane. Show
  or hide the raw image and mask overlay; adjust overlay colour/opacity.
- Select cells by clicking, entering comma-separated IDs, or drawing the viewer's
  selection rectangle. Inspect the selected IDs and **Clear selection**.
- Display cell IDs for **None**, **Selected**, or **All** cells.
- Show/hide track paths, display **all** or **selected** paths, choose path
  thickness, and show the full path or build it only to the current frame.
- Show/hide centroid markers, set their size, and use track-palette or single
  colours for the trajectory display.
- Filter by track length: less/greater than, inclusive comparisons, equal,
  not equal, or an inclusive range. **Filter** applies the values;
  **Clear filter** removes the filter.
- Enable **Crop**, draw/move/resize a rectangle or enter its dimensions, change
  its colour, use **Crop** to fit selected cells across time, and **Preview**
  to zoom to it.
- Give an optional export label and **Save current display** to a new TIFF
  with image data and ImageJ overlays, using the active crop when enabled.

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
