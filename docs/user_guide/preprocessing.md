# Preprocessing

[User guide](README.md) · [Previous: Runs and settings](runs_and_settings.md) ·
[Next: Segmentation](segmentation.md)

Preprocessing corrects alignment and image background before segmentation and measurement. Enable only the corrections you need. FITS executes channel registration, time registration, then background subtraction; disabled steps are bypassed.

Registration changes image geometry and can require [REF/ROI alignment review](reference_and_roi_masks.md#reuse-masks-after-processing-changes). Intensity-only background correction does not invalidate that geometry.

Choose reference, optional fit, and excluded channels from the exported channels; see [Channels and labels](channels_and_labels.md#exported-channels-and-downstream-choices).

For a control-by-control overview, see the
[time-registration](gui_tools.md#time-registration-preview-gui),
[channel-registration](gui_tools.md#channel-registration-preview-gui), and
[background-subtraction](gui_tools.md#background-subtraction-preview-gui)
preview feature lists.

## Registration tuning and accepted transforms

Click **Preview** in the Frame-shift or Channel-shift settings to open
RegTune on its **Time registration** or **Channel registration** tab. Both tabs
share the same image browser and navigation. When launched from the main GUI,
its current settings take priority over saved experiment tuning. In time registration,
channel changes in the top toolbar update the fitting channel. In channel registration,
selecting a reference also selects its display channel; browsing display channels
does not change the reference. An unset reference defaults to the first channel,
while an existing reference is preserved. Saving accepts the displayed reference.
**Run preview** fits the complete
time sequence or the channels at the selected reference frame in a background
worker; the button becomes **Cancel preview** while working. Z stacks use a
maximum projection for fitting, and the resulting 2D transforms apply to all Z
planes. OpenCV and pystackreg support translation, rigid-body, and affine;
scikit supports translation. Excluded channels stay unchanged and are not fitted.

### Choose an algorithm and context

Selecting a **Context** preset fills in its actual algorithm and method. They are
grouped under **Algorithm and method**, labelled **Set by context**. Editing either
selects the matching named context when one exists, otherwise **Custom** and
**Manual settings**. Returning to a preset's algorithm/method restores its context;
choosing a preset also restores its values. Custom is a viewer label only: saved settings
retain the last named context and explicit algorithm/method values.
Changing a registration context in the main settings panel also
updates its algorithm and method.

Registration TOML settings use `algorithm` for the implementation choice
(`scikit`, `pystackreg`, or `cv2`). Older `backend` keys are accepted when loading
settings and renamed to `algorithm` when saved.

Both tabs use three separate panels in the SegTune style: **Registration settings**,
**Fitting crop**, and **Resolved registration**. The first retains the registration
fields and algorithm/method group. Registration and crop settings scroll, while
the resolved panel stays fixed at the bottom of each tab. It shows the effective plan, for
example `pystackreg / translation / previous / full image` or `... / from crop`.
Channel registration shows its reference channel and frame instead of a time
reference strategy. The summary follows settings and enabled crop changes.

When SegTune or RegTune is opened from the main GUI, its run-directory field and
Browse button are disabled. Experiments within that run remain selectable.
Standalone tuners retain directory browsing.

### Fit using a crop

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

### Compare the registered image

For time registration, choose Original image, Registered image, or Composite overlay. The overlay
compares the original and registered images at the same frame, channel and Z
plane. The original is grayscale and the registered image uses the selected
channel LUT. When the registered image is grayscale, the original is magenta
instead. Both are auto-scaled separately and blended to show registration's
displacement. The canvas dimensions stay unchanged; transforms can leave empty
borders or move content outside the frame.

For channel registration, choose **Original alignment** or **Registered alignment**.
Both show a composite of the reference and the selected comparison channel.
Original alignment uses both original channels; Registered alignment keeps the
reference unchanged and transforms the comparison channel. **C** cycles included
comparison channels while keeping the reference fixed. If the selector names the
reference, the first included comparison is used. With one comparison, cycling
does not change the view. Excluded channels are skipped by C but can be selected
manually to inspect their unchanged original image. **V** switches before/after
for the current pair, keeping the same frame and Z plane. Both views
use the same colours and contrast, based on the original planes. Distinct channel
colours are used when available; otherwise the reference is magenta and the
comparison green. The tooltip identifies the pair. Registered alignment falls
back to original alignment until a matching preview is available. If no other
included channel exists, only the reference is shown.

**V** also switches original/registered images in time registration and
original/background-subtracted images in BGTune. **X** remains the mask-overlay
shortcut in mask tools and SegTune. Time registration keeps all channels available
to **C**; BGTune cycles only channels included in background subtraction.

Each tab previews its registration
directly on the source image; the Channel tab does not run time registration first.

### Save and reuse accepted settings

Each tuner opened from the main GUI edits a private copy of its settings.
**Save current settings** merges the active tab's values into the main GUI draft;
other pending tuner edits stay private. Closing without saving discards those
pending edits, including segmentation channel additions or deletions. Previously
applied changes remain in the main draft. **Save settings** and **Run pipeline**
in the main GUI write that draft to disk; processing starts only after saving succeeds.

**Save current settings** works with or without a preview. When opened from the
main GUI, it updates the GUI's editable settings without writing its TOML file.
It also caches the experiment's fitting crop, settings signature and any matching
fitted matrices in the acquisition's `.fits_experiment/tuning/<series>/registration/time.npz` or `channel.npz`.
Accepting changed manual algorithm/method overrides opens **Advanced settings**
in the main panel. Unchanged saves and named preset selections leave it
collapsed. All tuners preserve advanced sections the user already opened.
Save settings or Run pipeline in the main GUI persists the general settings,
as with SegTune. **Save current settings** saves only the selected tab and keeps
the viewer open for further time or channel tuning. **Close window** closes
without saving. If either used tab differs from the main GUI or has unsaved crop
changes, a warning offers **Keep editing** or **Close without saving**. The
title-bar close button uses the same warning. Save each changed tab explicitly;
a save failure leaves its changes unsaved and keeps the viewer open.
Without a matching preview, saving stores settings and the fitting rectangle
without matrices, replacing any older accepted transforms. The pipeline fits
those settings later. Saving never applies the whole stack. Preview caches are released when
the experiment changes or the viewer closes; the source image is not modified.

Both pipeline registration tasks use the settings saved by the main GUI or CLI
configuration. Cached tuning never overrides later changes to those settings.
They check accepted models before fitting. Matching settings,
fitting pixels, channel labels, and image dimensions allow matrix reuse; changed
input triggers fresh fitting with the configured settings. This also checks that
channel transforms tuned after time registration match the actual pipeline
input. Reuse avoids fitting, while resampling and saving images still run.
Delete the relevant tuning file to remove its saved fitting crop and transforms.

### Open RegTune independently

Standalone launch supports an initial image/folder, tab, and settings file:

```bash
uv run fits-regtune /path/to/experiment --mode channel --settings /path/to/fits_settings.toml
```

Standalone Save updates the supplied settings file, or the nearest saved FITS
settings found within the browser root. Without one, it creates
`<browser-root>/.fits/fits_settings.toml` from the template. The module launcher
`python -m fits.gui.viewer.registration` accepts the same arguments.

## Background-subtraction preview

Click **Preview** in the background-subtraction settings
section to open BGTune. It loads the GUI's current settings and selected
experiment, with run-directory browsing locked. Standalone `fits-bgtune` keeps
browsing and accepts an initial experiment/image, `--experiments-dir`, and
`--settings`, for example:

```bash
uv run fits-bgtune /path/to/experiment --settings /path/to/fits_settings.toml
```

The three actions sit to the right of the LUT, matching RegTune: orange **Run preview**,
dark green **Save current settings**, and light red **Close window**.
Run preview computes only the selected frame, channel
and Z plane in a worker. Navigating afterward computes only requested planes;
no neighboring frames or full stacks are prepared in the background. SMO's
configured processor is reused across same-sized planes with the same sigma
and window size. Window size must be at least 2 pixels (usually 3 or larger);
the SMO probability threshold is between 0 and 1. Visited results use an 8-plane/64 MiB cache (one oversized
current plane can remain displayable). Changing settings requires Run preview
again. Excluded channels pass through unchanged.

### Compare intensities and use the measurement box

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

### Save background settings

**Save current settings** accepts settings even without a preview and keeps the
tuner open. It transfers them
to the main GUI without changing whether the background-subtraction step is
enabled. Advanced settings opens only when an advanced value, such as threshold
or statistic, changes; basic edits leave it collapsed. Standalone saving updates the supplied
or nearest general settings file, or creates one at the selected run root.
Images are never overwritten by the tuner; the measurement box and preview
pixels are not saved. **Close window** checks processing settings for unsaved
changes and offers **Keep editing** or **Close without saving**. The title-bar
close button uses the same check. Measurement boxes and display controls do not
count as unsaved processing settings. Closing during processing waits for the
current plane to finish before releasing its resources.
The status bar reports each plane's processing time.
Press **R** to preview or **S** to save and stay open; **Info** lists the shortcuts.

## Check the saved result

Tuners preview changes and save settings; **Run pipeline** applies the enabled steps to the full data. Inspect the registered/background-subtracted output in the [image viewer](viewers.md). Signed corrected values can differ from their zero-clipped display copy; use the stored values for analysis.
