# FITS

FITS—Fluorescent Image Tracking Software—is a reproducible workflow for
processing and quantifying fluorescence-microscopy experiments. It brings image
conversion, registration, background subtraction, segmentation, tracking,
spatial profiling, and labeled-region extraction into one experiment-aware
pipeline.

The project is aimed at researchers who should not need to write Python to run
an analysis. Its desktop interface exposes pipeline settings and dedicated
viewers for segmentation tuning, reference masks, and ROI masks, while the CLI
supports scripted and repeatable runs. Both use the same settings models and
workflow engine.

## Design

FITS owns experiment discovery, scheduling, state, paths, provenance, and saved
artifacts. Numerical work is delegated to focused submodules that accept arrays
and can also be used independently:

- `fits_io` reads microscopy formats and writes metadata-rich FITS TIFFs.
- `stackalign` performs time-wise and cross-channel registration.
- `bg_sub` removes spatially varying image background.
- `cellpose_kit` provides a stable Cellpose v3/v4 segmentation interface.
- `tracklink` links segmented objects over time.
- `mask_interpolation` completes sparsely drawn reference and ROI masks.
- `bioimagequant` performs object extraction and distance-profile analysis.
- `progress_bar` provides terminal progress and controlled log display.

## Pipeline operation

`fits.pipeline.start_pipeline()` loads the TOML settings, discovers supported
raw images, restores saved experiment state, resolves overwrite decisions, and
runs enabled steps in this order:

```text
Convert → Preprocess → Process → Analysis
           |              |         |
           |              |         └─ distance profile, quantification
           |              └─ segmentation, tracking
           └─ time registration, channel registration, background subtraction
```

Every launch saves the input configuration, including its comments, as
`.fits/fits_settings.toml` in the run directory before processing starts. This also
applies when running `pipeline.py` with the packaged `user_settings.toml`,
so the GUI can later load the run's settings. The saved copy reflects the
latest launch and remains available if processing fails.

Each experiment has an `experiment_state.json` file containing its artifacts,
completed steps, metadata, and provenance. Artifact paths, rather than a second
workflow manifest, are the durable evidence used to resume work. Conversion can
split a raw file into several experiment branches. Re-running an unchanged step
reuses completed output; enabling overwrite rebuilds that step and requests
overwrite for later enabled steps. Conversion and preprocessing currently share
`fits_array.tif`: overwriting preprocessing does not automatically reconvert
the original source. Separate intermediate artifacts and provenance-based
archive selection remain planned in [the TODO list](docs/todos.txt).

The default conveyor execution lets prepared experiments advance while other
experiments are still upstream. In the interactive conveyor, reference/ROI
drawing can overlap with processing, while analysis waits for both its processed
image and finalized mask outcome. A failure is recorded for its experiment and
other experiments continue when possible. Preprocessing or processing failure
skips that experiment's downstream work; a user choosing to omit an optional
analysis input can produce a partial result. If every experiment fails, the
pipeline stops with an error.

Interactive-mask and conversion-only GUI runs write a timestamped log and full
text report under `.fits/logs/` and `.fits/reports/`, respectively. Reports list
completed, partial, skipped, and failed work by phase and experiment. The GUI
opens the latest report when a run
finishes; **Full Report** and report files in the directory browser can reopen
it later.

Quantification includes portable experiment paths and cell identifiers for
grouping measurements across intensity channels and time. See
[analysis identifiers](docs/analysis_identifiers.md) for their format, segmentation
behavior, and the deferred handling of independent Z planes.

## Installation

Install Git and [uv](https://docs.astral.sh/uv/getting-started/installation/),
then clone FITS into a folder writable by your normal user:

```bash
git clone https://github.com/BennyGinger/FITS.git fits
cd fits
```

On Linux, run `bash install_linux.sh`. On Windows, open `install_win.bat`
(or run it in a terminal). No globally installed Python or GPU is required:
uv obtains Python 3.12 and creates this checkout's single `.venv`.

The installer initializes the recorded submodules, runs ordinary `uv sync`,
checks GUI/backend imports and model-cache write access, and creates a per-user
Applications-menu entry on Linux or Start-menu shortcut on Windows. It does
not run the pipeline or request model weights. Model downloads happen on first
use. GPU availability is reported without making it an installation requirement.
Run as your normal user, rather than as administrator or with `sudo`.

Progress and subprocess errors are saved to `installation/logs/install.log`. If a
step fails, correct the reported problem and rerun the installer. Submodules
with local edits or commits differing from FITS's recorded versions cause the
installer to stop before changing their checkouts. No pull, reset, cleanup, or
automatic dependency upgrade is performed. If `uv sync` changes the lockfile,
the installer reports it for review.

Use `bash install_linux.sh --no-shortcut` or `install_win.bat --no-shortcut`
to omit the shortcut. If an existing FITS shortcut points to another checkout,
the installer asks before replacing it, after the new installation passes its
checks. The old folder is left untouched. Rerunning in the same location
refreshes that user's shortcut. Separate OS users should use their own writable
checkouts and environments.

Deleting a development checkout removes its code and `.venv`; save local work
and data first, including changes inside submodules. Per-user model/uv caches
and the shortcut remain. A fresh clone and installation recreate the environment
and can repoint the shortcut. If moving a checkout, recreate its `.venv` at the
new location and rerun the installer; virtual environments are not portable.

Automatic updates and startup repair are not included yet. Shortcuts currently
open the installed GUI directly.

### Manual development setup

Clone the repository together with its submodules, then synchronize the uv
workspace:

```bash
git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits
cd fits
uv sync
```

### Default GPU setup

Plain `uv sync` and `uv run` select the development defaults automatically:

- Windows x64 is configured for PyTorch 2.8.0+cu129 and torchvision
  0.23.0+cu129 from the CUDA 12.9 package index.
- Linux constrains PyTorch to 2.10.0 and torchvision to 0.25.0 and uses its
  existing package source. The Windows accelerator group does not apply there.

These describe the current dependency configuration, not a hardware validation.
Check GPU availability on the machine where FITS will run.

No extra flags are needed for everyday development:

```bash
uv run fits-gui
uv run fits-segtune
uv run cellpose
```

The shared default is `[tool.uv].default-groups = ["dev", "cuda129"]` in
`pyproject.toml`. To omit the Windows accelerator group:

```bash
uv sync --no-group cuda129
uv run --no-group cuda129 fits-gui
```

A later plain `uv sync` or `uv run` restores the shared default. The former
`cpu`, `cuda126`, and `cuda128` groups are not defined in the current project.
Omitting `cuda129` removes that group selection; it does not select a dedicated
CPU profile.

Check GPU availability from the FITS directory:

```bash
uv run python -c "import torch; from cellpose import core; print(torch.__version__, torch.version.cuda); print('Cellpose GPU:', core.use_gpu())"
```

Restart running Python sessions after changing PyTorch, and enable `use GPU`
in the Cellpose GUI (or pass `--use_gpu` to the Cellpose CLI).

Launch the main settings interface with `uv run fits-gui`, or open the image
tools directly:

```bash
uv run fits-segtune
uv run fits-drawmask
uv run fits-regtune
uv run fits-trackviewer --experiments-dir /path/to/run
uv run fits-trackedit /path/to/experiment/fits_track.tif
uv run fits-channel-labels /path/to/run
```

In the main GUI, **Channel Labels** sits between **Tracking Viewer** and
**Full Report**. It inspects every FITS artifact in the run directory, then
lets you rename labels by original source channel index. It maps channel
references in FITS TIFFs, measurement Parquets, experiment states, and saved
run settings, then writes only files that reference a changed label while
preserving image pixels and ImageJ overlays. A conflicting index-to-label
mapping stops the rename and names the affected files. The button is disabled
while the pipeline runs. The command line can inspect or preview the same run:

```bash
uv run fits channel-labels /path/to/run
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red --apply
```

On Ubuntu, install an Applications-menu launcher with the FITS logo:

```bash
.venv/bin/python scripts/install_linux_launcher.py
```

Search for **FITS** in Applications, then pin it to your favourites if desired.
The launcher uses this checkout's `.venv` directly, without opening a terminal
or syncing dependencies. Rerun the installer if you move the repository.

In `fits-gui`, each segmentation channel has its own settings section. Use
**+** beside the target channel to add a section, or **−** to remove one.
Each channel can use a different model, diameter, denoising option, and nuclear
helper channel. Execution and overwrite controls apply to the whole step.

Select a run directory with Browse, enter a path and press Enter, or drag one
local folder onto the main window or Run directory field. Folder selection loads
that run's saved settings, or fresh template settings if none exist. Folder
changes are blocked while the pipeline runs.

The **Activity log** header always shows a step label, progress bar, and elapsed
time. Batch runs mirror the current step's terminal counter; conveyor runs show
**Pipeline steps**, using the terminal Pipeline counter, including totals added
by output branches.
Conversion-only runs show **Convert**. Interactive runs show overall configured
stage completion as **Pipeline steps**. The elapsed clock has no time-remaining
estimate and freezes when work finishes; the blue activity indicator runs while
the pipeline is active.

Click **Tune segmentation…** to preview Cellpose with those settings.
SegTune and RegTune open the experiment selected in the main GUI, or the first
available `fits_array.tif` when the run folder or no experiment is selected.
The opened file is highlighted in the tuner's browser. Choosing an experiments
directory in a standalone tuner also opens its first available image.
SegTune shows a selectable list of channel configurations below its controls.
**Apply and add another channel** retains the current settings and selects
the next unused image channel. Click a row to revisit its settings, or its
trash button to remove it; the last row cannot be removed. Channels assigned
to other rows are excluded from the target selector. **Apply and close**
copies the entire channel list back to the main GUI. Closing the tuner without
applying leaves the main settings unchanged. Use Save settings or Run pipeline
in the main GUI to save the changes. Converted `fits_array.tif` images are
required for previewing. When an image is opened, SegTune initializes and caches
the selected Cellpose model in the background without running an automatic
preview. The tuning controls remain editable while it loads, but **Run preview**
stays disabled until the model is ready. Changing the built-in model, custom
model path, or denoising option queues the latest model for initialization.
Different initialized models remain cached in the Python process, so switching
back reuses the model. Keeping multiple models also uses more CPU/GPU memory.

Click **Tune background subtraction…** in the background-subtraction settings
section to open BGTune. It loads the GUI's current settings and selected
experiment, with run-directory browsing locked. Standalone `fits-bgtune` keeps
browsing and accepts an initial experiment/image, `--experiments-dir`, and
`--settings`, for example:

```bash
uv run fits-bgtune /path/to/experiment --settings /path/to/fits_settings.toml
```

The two actions sit to the right of the LUT: orange **Run preview** and dark
green **Save and close**. Run preview computes only the selected frame, channel
and Z plane in a worker. Navigating afterward computes only requested planes;
no neighboring frames or full stacks are prepared in the background. SMO's
configured processor is reused across same-sized planes with the same sigma
and window size. Window size must be at least 2 pixels (usually 3 or larger);
the SMO probability threshold is between 0 and 1. Visited results use an 8-plane/64 MiB cache (one oversized
current plane can remain displayable). Changing settings requires Run preview
again. Excluded channels pass through unchanged.

Choose **Original image** or **Background-subtracted image**, or press **V** to
switch rapidly with the same LUT and intensity limits. **Enable measurement
box** enables drawing, moving and resizing a rectangle. Its pinned results
show original and processed means and their difference, from the same raw pixel
coordinates. Measurements follow frame/channel/Z changes and ignore display
contrast. The rectangle only measures; processing always uses the full plane.
Background-subtracted arrays and preview caches retain signed `float32` values,
including negative and fractional residuals. Pipeline TIFF output also uses
`float32`; excluded channels keep their values in that dtype. Viewers show
negative pixels as zero in a separate display array. Box means and downstream
analysis use the signed values, not that display copy.

**Save and close** accepts settings even without a preview. It transfers them
to the main GUI and reveals Advanced settings without changing whether the
background-subtraction step is enabled. Standalone saving updates the supplied
or nearest general settings file, or creates one at the selected run root.
Images are never overwritten by the tuner; the measurement box and preview
pixels are not saved. The status bar reports each plane's processing time.
Press **R** to preview or **S** to save and close; **Info** lists the shortcuts.

Click **Tune registration…** in either registration settings section to open
RegTune on its **Time registration** or **Channel registration** tab. Both tabs
share the same image browser and navigation. When launched from the main GUI,
its current settings take priority over saved experiment tuning. Explicit channel
changes in the top toolbar update the active tab's fitting/reference channel. **Run preview** fits the complete
time sequence or the channels at the selected reference frame in a background
worker; the button becomes **Cancel preview** while working. Z stacks use a
maximum projection for fitting, and the resulting 2D transforms apply to all Z
planes. OpenCV and pystackreg support translation, rigid-body, and affine;
scikit supports translation. Excluded channels stay unchanged and are not fitted.

Selecting a **Context** preset fills in its actual backend and method. They are
grouped under **Backend and method**, labelled **Set by context**. Editing either
selects the matching named context when one exists, otherwise **Custom** and
**Manual settings**. Returning to a preset's backend/method restores its context;
choosing a preset also restores its values. Custom is a viewer label only: saved settings
retain the last named context and explicit backend/method values, with no CLI
schema change. Changing a registration context in the main settings panel also
updates its backend and method.

Both tabs use three separate panels in the SegTune style: **Registration settings**,
**Fitting crop**, and **Resolved registration**. The first retains the registration
fields and backend/method group. Registration and crop settings scroll, while
the resolved panel stays fixed at the bottom of each tab. It shows the effective plan, for
example `pystackreg / translation / previous / full image` or `... / from crop`.
Channel registration shows its reference channel and frame instead of a time
reference strategy. The summary follows settings and enabled crop changes.

When SegTune or RegTune is opened from the main GUI, its run-directory field and
Browse button are disabled. Experiments within that run remain selectable.
Standalone tuners retain directory browsing.

Each tab has a **Fitting crop** subpanel explaining that a smaller region can
focus on stable features when full-image fitting is difficult and speed up
live-preview fitting, while registration still applies to the full
image with unchanged output size. Its **Enable crop** toggle is off by default. Enable it to draw, move
or resize a fitting rectangle; **Preview** zooms to the rectangle so you can
check it while navigating frames. There is no automatic Crop action. Disabling
the tool hides the rectangle, returns to the full view and uses the full image
for fitting, even if a rectangle remains stored. The crop limits fitting only:
transforms are converted to full-image coordinates and never trim the output.

After fitting, both tabs apply transforms only to the frame, channel and Z plane
being displayed. Visited registered planes are cached, up to eight planes or
64 MiB per preview. Moving to another frame does not repeat fitting. Channel
fitting uses only its reference frame; full-stack application happens in the
pipeline, rather than delaying the interactive preview.

Choose Original image, Registered image, or Composite overlay. The overlay
compares the original and registered images at the same frame, channel and Z
plane. The original is grayscale and the registered image uses the selected
channel LUT. When the registered image is grayscale, the original is magenta
instead. Both are auto-scaled separately and blended to show registration's
displacement. The canvas dimensions stay unchanged; transforms can leave empty
borders or move content outside the frame. Each tab previews its registration
directly on the source image; the Channel tab does not run time registration first.

**Save current settings** works with or without a preview. It updates the
general settings in the main GUI and saves the accepted experiment's settings,
crop and any matching fitted matrices in `<experiment>/.fits/registration/time.npz` or `channel.npz`.
Accepting tuner settings checks **Advanced settings** in the main panel so the
effective backend and method remain visible.
Save settings or Run pipeline in the main GUI persists the general settings,
as with SegTune. **Save current settings** saves only the selected tab and keeps
the viewer open for further time or channel tuning. **Complete session** saves
both tabs, then closes the tuner; a save failure keeps the viewer open.
Without a matching preview, saving stores settings and the fitting rectangle
without matrices, replacing any older accepted transforms. The pipeline fits
those settings later. Saving never applies the whole stack. Preview caches are released when
the experiment changes or the viewer closes; the original `fits_array.tif` is
not modified.

Both pipeline registration tasks check accepted models before fitting. Tuned
experiments keep their accepted settings when general settings change. Matching
fitting pixels, channel labels, and image dimensions allow matrix reuse; changed
input triggers fresh fitting with the accepted settings. This also checks that
channel transforms tuned after time registration match the actual pipeline
input. Reuse avoids fitting, while resampling and saving images still run.
Delete the relevant tuning file to return an experiment to general settings.

Standalone launch supports an initial image/folder, tab, and settings file:

```bash
uv run fits-regtune /path/to/experiment --mode channel --settings /path/to/fits_settings.toml
```

Standalone Save updates the supplied settings file, or the nearest saved FITS
settings found within the browser root. Without one, it creates
`<browser-root>/.fits/fits_settings.toml` from the template. The module launcher
`python -m fits.gui.viewer.registration` accepts the same arguments.

The main settings interface groups steps into **Convert**, **Preprocess**,
**Process**, and **Analysis** tabs. The step list on the left shows only the
selected phase, and a `✓` in a tab title means that phase contains at least one
enabled step. When a run directory has no `fits_array.tif`, only Convert is
available and **Convert experiment(s)** performs a conversion-only pass. After
successful conversion, the other tabs unlock and the button becomes **Run
pipeline**. **Unlock all phase tabs** in advanced runtime settings allows a
single full run from raw inputs; artifact-dependent viewers remain disabled
until converted arrays really exist.

For enabled steps, the GUI requires conversion channel labels, a channel-
registration reference channel, at least one segmentation channel, and at
least one tracking channel. If one is missing, the GUI keeps the affected step
or phase selected and explains which field must be completed. **Run pipeline**
remains disabled until all required fields belonging to enabled steps have a
value. These checks detect omitted input only; the pipeline continues to handle
invalid channel names and other data-dependent validation.

Enable **Edit tracking** in the Process phase to review each active tracking
artifact after automatic tracking and before analysis. FITS opens the full
tracking editor with the experiment's `fits_array.tif`; the displayed image
channel can be changed independently from the mask channel and is the channel
used by local mask prediction. **Save edited tracking** writes
`fits_track_edited.tif`, or `fits_track_edited_filtered.tif` when track-length
filtering is enabled, and makes that copy the experiment's active tracking
artifact. The original `fits_track.tif` remains in place. **Use original
tracking** completes the optional step without replacing it. Quantification
then consumes only the active tracking artifact. Enable overwrite to reopen a
previously completed edit.

Standalone `fits-trackedit /path/to/experiment/fits_array.tif` starts an empty
tracking session without an existing tracking mask. Add/Edit uses headless
micro-SAM with positive/negative prompts and an expected cell diameter defining
the local crop. Predict, inspect or brush-correct the proposal, then accept it;
accepted masks determine the centroids used for trajectories. Manual brush and
enclosed-fill operations remain separate from inference, as does the Split
predictor. The editor supports track merge/link, stopping or unlinking a track,
mask/track deletion, and undo. Saves use the edited-tracking filenames above
and record compact edit provenance. Redo, a replayable per-edit log, and the
static-only temporal policy remain pending; see the
[tracking TODOs](docs/todos.txt) and [micro-SAM cleanup plan](docs/microsam_tracking_cleanup.md).

`fits-drawmask` opens a dedicated mask editor with **Reference** and **ROI**
tabs sharing the same experiment and image controls. `fits-segtune` opens its
own segmentation window; standalone **Apply and close** ends the tuning
session without writing a pipeline settings file. Launch the tuner from
`fits-gui` to transfer its settings back and save them.
Opening an image also loads the first reference and ROI masks beside it, in
filename order. Selecting a mask file opens its sibling image and that specific
mask in the matching tab.
The former `fits-viewer` command has been removed.

Segmentation tuning, Reference/ROI, and tracking viewers read image and mask
planes on demand through `fits_io`, as does registration tuning. Each plane cache holds at most eight planes
and 64 MiB. Edited mask planes are stored separately in a private temporary
directory and remain available when you move between frames. Save writes the
usual mask artifacts; closing the session removes its temporary edits. Tracking
saves assemble a disk-backed array plane by plane.
Reference/ROI live propagation previews prepare one selected-channel T or Z
sequence in a background thread and cache its completed mask states in a private
temporary directory under the experiment's `.fits/viewer_cache/`. Navigating
within that sequence reads cached planes without repeating interpolation.
The current plane and nearby planes are prepared first; moving the slider
reprioritizes remaining work. Ready planes are immediately usable, while a
missing preview has a translucent, fading loading overlay and a status/progress
indicator. Edits, undo, channel/depth changes, and propagation settings select
or invalidate the corresponding preview; stale background results are discarded.
Each drawing session retains one completed sequence. Temporary previews are
removed when replaced or the viewer closes, and read-only experiments fall back
to the system temporary directory. Source masks and ROI threshold/manual states
are preserved. Preview caches are session-local and do not reload unsaved work
on a later launch.
Saving with propagation reuses a matching cached sequence, calculating only
uncached sequences. ROI caches retain threshold and manual-edit states as well
as the information needed for display. Saving copies cached sequences directly to output storage and uses faster
lossless zlib compression (level 1), trading slightly larger files for speed.
Unsaved-work bookkeeping checks and copies only edited planes. Merging existing mask channels
and segmentation volume previews use their existing stack/volume routines.
Completing an unchanged drawing session checks channel revisions instead of
reading and comparing the full mask stacks.
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

Tracking centroids and trajectory drawings are prepared in the background, with
progress and the current stage shown at the bottom right. Frame navigation reuses
already-drawn, native-resolution trajectory overlays for every frame. These
are prepared once in disk-backed storage, so forward navigation and arbitrary
frame jumps need no trajectory redraw. Both the tracking viewer and editor keep
completed drawings in `.fits/viewer_cache/tracking_paths/` and load them on
reopening, without scanning mask pixels or drawing the paths again. Cache keys
include the source file stamp, channel/Z, actual centroid coordinates (including
filters and unsaved edits), and drawing style. Changed inputs therefore get a
new drawing; cancelled or incomplete drawings are never reused. Selection IDs
and white highlights use cached coordinates in a separate lightweight layer
and do not rebuild the base drawing.

In the read-only tracking viewer, **Save current display** writes a new
`fits_track_overlay[_filtered][_label].tif`: all channels, Z planes, and frames
from `fits_array.tif`, with their original pixel values, plus an embedded ImageJ
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

The viewer's cached trajectory overlays use four bytes per pixel per frame and are mapped from disk;
they are not loaded into RAM in full. The persistent cache retains up to four
recent drawings within 2 GiB, always keeping the latest complete drawing even
when that drawing alone exceeds the limit. Older drawings are removed as needed.
Read-only experiments use temporary drawings instead. The first preparation,
changed settings, and drawings evicted from the cache still require work;
reopening a matching cached drawing only loads metadata and maps its pixels.
Edits and undo invalidate only affected centroid frames. Compressed
`.fits/viewer_cache/<mask filename>.centroids-c*-z*.npz` files inside each
experiment store centroid tables and all track lengths. They load automatically;
changed source files invalidate them. Valid legacy hidden caches beside masks
migrate to this folder on use. On read-only folders the viewer keeps its
in-memory cache if it cannot write the persistent cache.
Length filters use inclusive first-to-last frame spans, including gaps, matching
quantification's `track_length`. Filter results reuse the cached lengths rather
than rescanning observations. Recent trajectory drawings are reused for filters
selecting the same tracks with the same style. This in-memory drawing lookup
retains at most four entries and 2 GiB; a drawing larger than this limit remains
usable as the active display but is not retained in the in-memory lookup for later
reuse; its completed disk cache remains available. New filter results prepare
their first drawing in the background. Edits clear stale drawings, and closing
or switching experiments releases the in-memory lookup. Filter controls remain
editable and only apply when **Filter** is pressed; **Clear filter** restores
all tracks without resetting the entered values.
Viewers initially select the image channel matching the first loaded mask channel.

To open the collection panel in preview mode without running the pipeline:

```bash
uv run fits-drawmask --tool pipeline
```

Click **Load test experiments…** and choose a folder containing prepared
`fits_array.tif` images. The panel starts in Reference mode. **Go to ROI** /
**Go to ref** switches between Reference and ROI; unsaved changes require confirmation before
being discarded. New experiments join the waiting list without replacing the
current drawing. **Complete ref masks** or **Complete ROI masks** finalizes that
mask type and moves to the other one; completing the second type finishes the
experiment. **Next experiment** finishes the current experiment after any
needed warnings, and remains unavailable until the next queued experiment is
ready. **Complete session** ends collection normally; **Quit pipeline** is a
separate cancellation action. Buttons explain their actions when hovered.
Unsaved-change baselines retain lightweight plane references rather than copying
both mask stacks when opening or switching experiments. Only edited planes need
pixel comparisons, and saved channels update their references without stack copies.

The experiment tree shows all received experiments, highlights the current one,
and lists saved masks underneath each folder. Click a current experiment's mask
to reload it for editing. Masks from other experiments open for viewing only;
**Return to current experiment** restores your ongoing drawing. Newly saved
masks appear in the tree immediately.

**Load test experiments…** is only present in this preview. In the integrated
window, the pipeline supplies prepared experiments automatically; there is no
manual folder loader.

This is a preview with no running pipeline, but **Save writes real mask files**
to the selected experiment folders. The regular `fits-drawmask` command keeps
the standalone browser and visible tabs.

You can also supply `--experiments-dir /path/to/run` and
`--settings /path/to/fits_settings.toml`. Without a settings file, the preview
requests one reference per experiment and no ROI. With settings, it uses the
enabled extraction/distance-profile steps and their drawing options.

To run the connected drawing workflow with slow demonstration steps:

```bash
uv run fits-gui --demo-step-delay 5
```

Choose your run folder and settings in the main GUI, enable **Distance profile**
(or **Quantification → Draw reference masks**), then click **Run pipeline**.
The drawing window opens automatically once the first image is prepared.
Preparation continues for the other experiments, so the queue grows while you
draw. Completing an experiment's masks releases its analysis. Missing
references omit distance profiling for that experiment; no ROI means
whole-image profiling after confirmation.

The delay is five seconds between steps, including between arrivals when images
are already prepared. Ordinary `uv run fits-gui` has no artificial delay.
Interactive runs currently use one preparation worker and one downstream worker;
existing noninteractive batch/conveyor execution remains available. **Quit
pipeline** stops new work and waits for any already-running step to finish.
The drawing requests and early-finish choices are currently run-local; reopening
a run reuses saved masks and asks for finalization again.

The command-line interface is available through `uv run fits --help`. Running
`uv run fits run path/to/settings.toml` launches the same Ref/ROI collection
window when the configured analyses request interactive masks. Calling
`start_pipeline()` directly stays noninteractive unless a mask interaction
bridge is supplied.

Runtime `log_dir` overrides the root for FITS metadata. FITS creates
`.fits/logs/` and `.fits/reports/` below that root; when `log_dir` is empty,
both are created below `run_dir`.

## Repository maintenance

FITS uses Git submodules and a uv workspace. The practical commands for
cloning, updating, editing, adding, and removing submodules are collected in
the [Git and submodule cheatsheet](docs/git_cheatsheet.md).
