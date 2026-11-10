# Runtime and viewer internals

[Developer documentation](README.md)

## Reference

Existing material moved from the project README; it has not been rewritten into a new walkthrough.

### Conveyor execution

The default conveyor execution lets prepared experiments advance while other
experiments are still upstream. In the interactive conveyor, reference/ROI
drawing can overlap with processing, while analysis waits for both its processed
image and finalized mask outcome. A failure is recorded for its experiment and
other experiments continue when possible. Preprocessing or processing failure
skips that experiment's downstream work; a user choosing to omit an optional
analysis input can produce a partial result. If every experiment fails, the
pipeline stops with an error.

### Plane storage and propagation previews

Segmentation tuning, Reference/ROI, and tracking viewers read image and mask
planes on demand through `scope_io`, as does registration tuning. Each plane cache holds at most eight planes
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

### Preparing tracking trajectories

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

### Tracking caches and invalidation

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
changed source files invalidate them. Valid older hidden caches beside masks
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

### Interactive drawing demonstration

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
