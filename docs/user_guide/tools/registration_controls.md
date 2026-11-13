# Shared registration preview controls

[Guide home](../README.md)

Related: [Preprocessing](../preprocessing.md) · [Time preview](time_registration.md) · [Channel preview](channel_registration.md) · [Viewer controls](viewer_controls.md)

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
fitted matrices in the acquisition's `.acquisition/tuning/<series>/registration/time.npz` or `channel.npz`.
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
uv run fisch-regtune /path/to/experiment --mode channel --settings /path/to/settings.toml
```

Standalone Save updates the supplied settings file, or the nearest saved FIScH
settings found within the browser root. Without one, it creates
`<browser-root>/.pipeline/settings.toml` from the template. The module launcher
`python -m fisch.gui.viewer.registration` accepts the same arguments.
