# Background-subtraction preview

[Guide home](../README.md)

Related: [Preprocessing overview](../preprocessing.md) · [Settings](../settings/background_subtraction.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

Open **Background subtraction → Preview** to use BGTune.

- Adjust SMO **Window size** (at least 2), Gaussian **Sigma**, background
  **Threshold** (0–1), and **Statistic** (median or mean).
- Select excluded channels and set **Overwrite existing pipeline output**.
- **C** cycles included channels only. Excluded channels remain available in the
  channel menu for inspection and pass through unchanged.
- **Run preview** on the displayed frame/channel/Z plane. Afterward, navigate
  to calculate other requested planes; rerun preview after changing settings.
- Switch between **Original image** and **Background-subtracted image** while
  keeping the same display limits.
- Enable a **measurement box**; draw, move, resize, or set its width/height,
  choose its rectangle colour, and zoom to it. Read the original mean, corrected
  mean, and their difference. The box measures a region; subtraction uses the
  full image plane.
- **Save current settings** accepts settings, with or without a preview, and
  keeps the tuner open. **Close window** offers **Keep editing** or **Close without
  saving** when processing settings are unsaved. The title-bar close button uses
  the same check. Saving does not overwrite the image or save the measurement box.

## Background-subtraction preview

Click **Preview** in the background-subtraction settings
section to open BGTune. It loads the GUI's current settings and selected
experiment, with run-directory browsing locked. Standalone `fisch-bgtune` keeps
browsing and accepts an initial experiment/image, `--experiments-dir`, and
`--settings`, for example:

```bash
uv run fisch-bgtune /path/to/experiment --settings /path/to/settings.toml
```

The three actions sit to the right of the LUT, matching RegTune: orange **Run preview**,
dark green **Save current settings**, and light red **Close window**.
Run preview computes only the selected frame, channel
and Z plane in a worker. Navigating afterward computes only requested planes;
no neighboring frames or full stacks are prepared unless Show profile explicitly
requests a time/Z profile. SMO's
configured processor is reused across same-sized planes with the same sigma
and window size. Window size must be at least 2 pixels (usually 3 or larger);
the SMO probability threshold is between 0 and 1. Visited results use an 8-plane/64 MiB cache (one oversized
current plane can remain displayable). Changing settings requires Run preview
again. Excluded channels pass through unchanged.

### Compare intensities and draw measurement areas

Choose **Original image** or **Background-subtracted image**, or press **V** to
switch with the same LUT and intensity limits. **Draw** provides rectangle,
ellipse and polygon selections that can be moved and reshaped. The compact
**Intensities** box below the LUT buttons shows a hovered pixel when no area is
selected, the original **Mean** before preview, and **Original** / **BGSub** means
after preview. Measurements follow frame/channel/Z changes and ignore display
contrast. Areas only measure; processing always uses the full plane.
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

Tuners preview changes and save settings; **Run pipeline** applies the enabled steps to the full data. Inspect the registered/background-subtracted output in the [image viewer](../viewers.md). Signed corrected values can differ from their zero-clipped display copy; use the stored values for analysis.

### Drawing and live profiles in BGTune

BGTune shares the File Viewer's Draw controls and compact Intensities box.
Rectangle is the default; ellipse and polygon areas can also be drawn, moved,
and reshaped. With no area, the box shows the hovered pixel of the displayed
image. An area shows its original **Mean** before Run preview. After preview,
two columns show **Original** and **BGSub** means, including signed values.
Changing processing settings invalidates the processed measurement until the
next preview. Drawing does not enable processing or crop the input.

**Show profile** opens a live plot across time frames or Z planes. After Run
preview, the plot contains separate Original and BGSub curves; calculating them
processes the required full planes on demand in a background worker. The
Original curve appears first, and BGSub fills in progressively. The current
preview plane is reused; prepared full planes are retained in temporary mapped
files, so moving the area or reopening the plot does not repeat subtraction.
Changed numerical settings invalidate processed cached planes. The first full
BGSub profile still requires processing previously unseen planes. Changing
the area or the fixed frame/plane updates the open plot. The original images
and pipeline outputs are unchanged. BGTune has no crop/export-crop controls.
