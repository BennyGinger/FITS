# Reference and ROI masks

[User guide](README.md) · [Previous: Tracking](tracking.md) ·
[Next: Analysis and results](analysis_and_results.md)

Reference (REF) masks define the geometry from which distances are measured. ROI masks define which image pixels contribute to an ROI-restricted distance profile. Drawing names and drawing channels are distinct; see [Channels and labels](channels_and_labels.md#what-does-label-mean).

See the separate feature lists for the
[reference-mask tool](gui_tools.md#reference-mask-gui),
[ROI-mask tool](gui_tools.md#roi-mask-gui), and
[pipeline drawing session](gui_tools.md#pipeline-drawing-session-controls).

## Draw masks during analysis

Enable the drawing options for the relevant analysis. Distance profiling requires a reference; quantification can use references for distance measurements. The pipeline opens its drawing window when prepared images are ready and supplies further experiments as processing progresses. Draw and save the requested masks, then use **Next experiment** or **Close window**. Saved masks can be reused on later runs. Missing references omit distance profiling for that experiment; choosing no ROI permits whole-image profiling after confirmation.

## Drawing and navigation

Use Brush or Freehand polygon, navigate frames/Z planes, and inspect any interpolation before saving. Shared movement, clearing, selection, and keyboard controls are described in [Image and mask viewers](viewers.md#drawing-selection-and-keyboard-shortcuts). For naming and channel roles, see [Channels and labels](channels_and_labels.md).

## Reuse masks after processing changes

Saved REF/ROI drawings depend on registration geometry, not image intensity revisions. Background subtraction alone does not require redrawing them. Rerunning registration can flag their alignment for review; inspect the drawing over the current image, then accept its alignment through **Manage files** or correct/recreate it. See [file management](reprocessing_and_file_management.md#review-refroi-alignment).

## Standalone drawing tools

`fisch-drawmask` opens a dedicated mask editor with **Reference** and **ROI**
tabs sharing the same experiment and image controls.
Opening an image also loads the first reference and ROI masks beside it, in
filename order. Selecting a mask file opens its sibling image and that specific
mask in the matching tab.
The former `fisch-viewer` command has been removed.

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
