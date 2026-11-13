# Segmentation

[Guide home](../README.md)

Related: [Overview](../segmentation.md) · [Processing workflow](../first_analysis.md) · [Segmentation preview](../tools/segmentation.md) · [Channels and labels](../channels_and_labels.md) · [Shared settings](common.md)

Create cell/object masks from one or more exported image channels. Open
**Process → Segmentation** and configure one entry per target channel.

## Per-channel settings

| Parameter / action | Practical meaning |
| --- | --- |
| Channel to segment | Required target image channel; choose one channel per entry. |
| + / − | Add or remove target-channel entries. |
| Nuclear channel (optional) | A single helper channel, or None. |
| Built-in / custom model | Choose a discovered Cellpose model or supply a custom model file. |
| Diameter | Integer object diameter in pixels; 0 requests automatic sizing. |
| Flow threshold (>=0) | Higher values accept more masks; 0 disables flow-error filtering. Values above 1 are meaningful. Native 3D ignores this filter. |
| Cell probability threshold (−6 to 6) | Lower values find more/larger masks; higher values suppress dim detections. |
| Denoise | Optional preprocessing when supported by the installed Cellpose implementation. |
| Process in 3D / Stitch threshold (0–1) / Anisotropy | Z-stack options; 0 disables stitching. Availability depends on the data and installed model. |
| Preview | Open the segmentation preview for representative frames. |

## Models, diameter, and flow threshold

Segmentation's main settings use the installed Cellpose built-in model list,
matching SegTune. FIScH opens before loading Cellpose; model choices are discovered
once in a background thread while other settings remain editable. Saved model
selections stay visible; empty model controls show **Loading models…** until
discovery finishes. An early segmentation **Preview** request waits for that
same task, and Preview reuses its cached model choices and imported backend.
This discovery does not load model weights or change CLI pipeline behavior.
Diameter is entered as an integer. Flow threshold is a
nonnegative squared-error cutoff: values above 1 are meaningful, and 0 disables
flow-error filtering. Native 3D segmentation ignores this filter.

## Output

Writes `proc_masks_seg.tif`. Masks contain numeric object labels; segmentation
identifies objects per frame. Tracking links identities through time. Rerunning
segmentation can make downstream tracks and measurements outdated.

## Per-channel segmentation settings

In `fisch-gui`, each segmentation channel has its own settings section. New
sections start with an empty target channel; enter its name explicitly before
running segmentation. Use
**+** beside the target channel to add a section, or **−** to remove one.
Each channel can use a different model, diameter, denoising option, and nuclear
helper channel. Execution and overwrite controls apply to the whole step.

## Run and inspect segmentation

Save the preview settings, return to the main GUI, enable Segmentation, and use **Run pipeline**. Inspect `proc_masks_seg.tif` with [Image / Mask Viewer](../viewers.md). For changes to existing masks, review the [overwrite choices](../reprocessing_and_file_management.md#review-overwrites-and-input-conflicts). Tracking and measurements based on an older mask may need rerunning.
