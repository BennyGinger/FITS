# Reference and ROI masks

[Guide home](README.md)

Related: [Reference editor](tools/reference_masks.md) · [ROI editor](tools/roi_masks.md) · [Mask collection](tools/mask_collection.md) · [Analysis](analysis_and_results.md)

Reference (REF) masks define the geometry from which distances are measured. ROI masks define which image pixels contribute to an ROI-restricted distance profile. Drawing names and drawing channels are distinct; see [Channels and labels](channels_and_labels.md#what-does-label-mean).

See the separate feature lists for the
[reference-mask tool](tools/reference_masks.md),
[ROI-mask tool](tools/roi_masks.md), and
[pipeline drawing session](tools/mask_collection.md).

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

The [Pipeline mask collection](tools/mask_collection.md) page explains queued
experiments, expected-mask slots, saving, deletion and finishing a drawing session.
