# Segmentation

[User guide](README.md) · [Previous: Preprocessing](preprocessing.md) ·
[Next: Tracking and corrections](tracking.md)

Segmentation produces labeled cell masks from an exported image channel. Set up one section per channel you want to segment, choose a model and diameter, and inspect representative frames before running the whole dataset.

See [Channels and labels](channels_and_labels.md) for mask channels versus image channels and numeric object labels.

The [segmentation preview](gui_tools.md#segmentation-preview-gui) and
[compartment preview](gui_tools.md#compartment-preview-gui) each have a separate
list of available controls and actions.

## Per-channel segmentation settings

In `fits-gui`, each segmentation channel has its own settings section. New
sections start with an empty target channel; enter its name explicitly before
running segmentation. Use
**+** beside the target channel to add a section, or **−** to remove one.
Each channel can use a different model, diameter, denoising option, and nuclear
helper channel. Execution and overwrite controls apply to the whole step.

## Models, diameter, and flow threshold

Segmentation's main settings use the installed Cellpose built-in model list,
matching SegTune. FITS opens before loading Cellpose; model choices are discovered
once in a background thread while other settings remain editable. Saved model
selections stay visible; empty model controls show **Loading models…** until
discovery finishes. An early segmentation **Preview** request waits for that
same task, and Preview reuses its cached model choices and imported backend.
This discovery does not load model weights or change CLI pipeline behavior.
Diameter is entered as an integer. Flow threshold is a
nonnegative squared-error cutoff: values above 1 are meaningful, and 0 disables
flow-error filtering. Native 3D segmentation ignores this filter.
Settings changed while conversion is running apply to the next conversion.

## Segmentation and compartment previews

Click **Preview** in the segmentation settings to preview Cellpose with those settings.
SegTune opens the experiment selected in the main GUI, or the first
available image when the run folder or no experiment is selected. The tuner
opens the image stage used as input for the selected step. The opened file is
highlighted in the tuner's browser. A standalone tuner opens the first available
image when a directory is selected.
SegTune combines **Segmentation** and **Compartment** tabs, styled like the
main workflow's step tabs, with blue/green backgrounds and titles above the
image. Segmentation Preview opens the Segmentation tab; Quantification's
Compartments Preview opens Compartment. The segmentation tab loads the saved
segmentation mask. Compartment loads the active tracking result (including
accepted edits/filtering), otherwise segmentation. A source indicator identifies
the saved mask or temporary segmentation preview. If no suitable mask exists,
an initial segmentation preview is generated.

Both tabs have **Run preview**, **Save current settings**, and a red **Close**
button. Run preview generates/reuses segmentation using its current settings;
Compartment then displays membrane rings. These previews never overwrite saved
source masks. Membrane thickness reuses cached distance maps; dilation or a new
mask revision rebuilds the geometry. Changed segmentation settings mark a
previous result as out of date until previewed again.

Segmentation retains a selectable channel-settings list. **Add channel**, beside
its heading, creates an entry for the next unused image channel. Each row's bin
removes that entry from the tuner's private draft; the last entry cannot be removed.
The main GUI changes only when **Save current settings** is pressed. It applies
all segmentation channel entries and keeps the window open. Compartment's
**Mask channels** list selects the mask geometry without add/remove controls.
The image-channel selector independently changes the fluorescence background:
for example, red-derived masks can be inspected over the green image channel.
Thickness and dilation are shared across mask channels. Saving the Compartment
tab copies only its options into Quantification.

Each tab remembers its display colour: **Palette**, a preset solid colour, or
**Custom…**. Opacity and visibility remain adjustable. Colours affect display
only, without changing labels or processing settings. Closing warns about
unsaved processing settings in either tab, including channel additions and deletions.
Closing without saving discards pending changes; previously applied settings remain
in the main GUI draft. Use Save settings or Run
pipeline to persist the updated settings. Standalone saves update the run's
normal settings file; `fits-segtune [image-or-folder] --tab compartment` selects
the Compartment tab directly.

When segmentation is needed, the selected Cellpose model initializes in the
background. Changing model or denoising options queues the latest model for
initialization. Initialized models remain cached in the Python process, so
switching back reuses them; retaining several models uses additional CPU/GPU
memory.

## Run and inspect segmentation

Save the preview settings, return to the main GUI, enable Segmentation, and use **Run pipeline**. Inspect `fits_masks_seg.tif` with [Image / Mask Viewer](viewers.md). For changes to existing masks, review the [overwrite choices](reprocessing_and_file_management.md#review-overwrites-and-input-conflicts). Tracking and measurements based on an older mask may need rerunning.
