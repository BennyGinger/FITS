# Segmentation preview

[Guide home](../README.md)

Related: [Segmentation overview](../segmentation.md) · [Compartment preview](compartments.md) · [Settings](../settings/segmentation.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

Open **Segmentation → Preview** to use the Segmentation tab in SegTune.

- Select a channel-settings entry; **Add channel** or remove an entry with
  its bin button. The last entry cannot be removed.
- Select a **Built-in model**, or browse for a **Custom model** file. A supplied
  custom model takes priority. The panel identifies the installed Cellpose version.
- Set integer **Diameter**, **Flow threshold**, **Cell probability**, optional
  **Denoise**, and optional **Nuclear channel**. A diameter reference disk helps
  compare the selected size with the image.
- For suitable Z stacks, select **Process in 3D**, **Stitch threshold**, and
  **Anisotropy** as appropriate. Availability/behavior depends on the data and
  Cellpose backend.
- **Run preview**, navigate the image, and inspect the resulting masks. Show/hide
  them, adjust opacity, and choose a palette, solid colour, or custom colour.
- **Save current settings** saves the segmentation channel entries and keeps
  the tuner open. **Close** checks for unsaved changes. Channel additions and deletions stay in the tuner draft until saved.

Preview masks do not replace the saved source segmentation artifact.

## Working with segmentation previews

The tuner opens the experiment selected in the main GUI, or the first available
image when the run folder/no experiment is selected. It uses the image stage
that feeds segmentation and highlights that file in its browser. Opening a
standalone directory selects its first available image. The Segmentation tab
loads its saved segmentation mask when present; previews never replace that file.

**Add channel** chooses the next unused image channel. The bin removes an entry
from the private tuner draft; the last entry cannot be removed. Save applies all
segmentation entries to the main draft. Closing without saving discards pending
additions, deletions and parameter edits; previously applied changes remain.
Use **Save settings** or **Run pipeline** in the main GUI to persist the draft.
Standalone saving updates the run's normal settings file.

Each tab remembers its display colour (palette, solid colour or custom colour).
Opacity, visibility and colours affect display only. Changing segmentation
settings marks the previous preview as outdated until it is run again.

Models initialise in the background. Changing model/denoising options queues the
latest model; switching back can reuse a cached model. Retaining several models
uses additional CPU/GPU memory.

Standalone launch: `uv run fisch-segtune /path/to/image-or-folder`.
