# Pipeline mask collection

[Guide home](../README.md)

Related: [Drawing workflow](../reference_and_roi_masks.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

The collection window adds workflow controls around the REF and ROI tools:

- Inspect queued experiments and saved masks in the experiment tree; open a
  saved mask, then **Return to current experiment** to resume the active drawing.
- Switch between **Reference** and **ROI** tabs without discarding drawings.
- Manage each tab's masks below its scrollable settings. **Add mask** creates
  an expected slot; its bin removes the slot and reduces the expected count.
  Empty placeholders need no confirmation. Saved-mask deletion confirms before
  permanently deleting the file from disk.
- Enter a compulsory label and click the green **Save mask** button.
- Advance with **Next experiment** or finish collection with **Close window**.
  Both actions check missing masks and unsaved work in both tabs.
- Closing the viewer leaves pipeline continuation to the main application.
  Stop a run from the main GUI or with Ctrl+C in the CLI.
- The standalone collection preview additionally offers **Load test experiments…**;
  the integrated pipeline supplies experiments automatically.

## Collection-panel preview and experiment navigation

To open the collection panel in preview mode without running the pipeline:

```bash
uv run fisch-drawmask --tool pipeline
```

Click **Load test experiments…** and choose a folder containing prepared
FIScH image artifacts. The **Reference** and **ROI** tabs each manage their own
masks. Switching tabs or mask entries keeps unsaved drawings. New experiments
join the waiting list without replacing the current drawing.

Each tab has a fixed **REF masks** or **ROI masks** panel below its scrollable
settings. Requested masks initially appear as numbered **Expected mask** slots.
**Add mask** adds an empty slot and increases the expected count. Starting a
drawing identifies its channel; entering a label names the mask. A label is
compulsory: clicking **Save mask** without one highlights the label field and
shows a red status warning.

Each slot has a bin button. Removing an empty placeholder reduces the expected
count without confirmation. Deleting a saved mask requires confirmation and
**permanently deletes its file from disk**, as well as removing the slot.
Unsaved drawings require confirmation before deletion.

**Next experiment** finishes the current experiment after checking missing
masks and unsaved work in both tabs. During processing, it remains unavailable
until the next queued experiment is ready or preparation has finished.
**Close window** checks both tabs and ends mask collection; the main pipeline
decides how to continue with the saved masks. This viewer has no pipeline-stop
action. Use the main GUI's stop control or Ctrl+C in the CLI to stop a run.

The experiment tree shows all received experiments, highlights the current one,
and lists saved masks underneath each folder. Click a current experiment's mask
to open its editing slot. Masks from other experiments open for viewing only;
**Return to current experiment** restores your ongoing drawing. Newly saved
masks appear in the tree immediately.

**Load test experiments…** is only present in this preview. In the integrated
window, the pipeline supplies prepared experiments automatically; there is no
manual folder loader.

This is a preview with no running pipeline, but **Save writes real mask files**
to the selected experiment folders. The regular `fisch-drawmask` command keeps
the standalone browser and visible tabs.

You can also supply `--experiments-dir /path/to/run` and
`--settings /path/to/settings.toml`. Without a settings file, the preview
requests one reference per experiment and no ROI. With settings, it uses the
enabled extraction/distance-profile steps and their drawing options.
