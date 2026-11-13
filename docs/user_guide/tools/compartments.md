# Compartment preview

[Guide home](../README.md)

Related: [Analysis overview](../analysis_and_results.md) · [Segmentation preview](segmentation.md) · [Settings](../settings/quantification.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

Open **Quantification → Compartments → Preview**, or select SegTune's
**Compartment** tab.

- Enable/disable **Measure compartments**.
- Adjust **Membrane thickness** and **Cell expansion**, both in pixels.
- Enable/disable **Save compartment masks** for the later quantification run.
- Select a **Mask channel** from the loaded masks. This list inspects existing
  mask channels; it does not add or remove segmentation entries.
- Select the image channel independently to inspect those masks over another
  fluorescence signal. The source indicator identifies the active tracking mask,
  segmentation mask, or temporary segmentation preview being used.
- **Run preview** to generate/reuse the required masks and inspect compartment
  geometry, including membrane rings. Adjust mask visibility, opacity, and colour.
- **Save current settings** transfers the compartment options to Quantification
  without applying unrelated segmentation edits. **Close** checks for unsaved work.

Geometry settings apply to all mask channels. Previewing does not write the
exported compartment TIFFs; the quantification step creates them when enabled.

## Opening and saving

The preview uses the selected experiment and the image stage required by the
step. Its source indicator identifies the active tracking mask, otherwise
segmentation, or a temporary segmentation preview when a suitable saved mask
is unavailable. The image channel is independent from the mask channel: inspect
red-derived masks over green fluorescence, for example.

Membrane-thickness changes reuse cached distance maps; dilation or a changed
mask revision rebuilds geometry. Thickness and expansion apply to all mask
channels. Saving this tab applies only compartment options to Quantification.
Pending segmentation edits remain private until saved on that tab.

**Close** checks unsaved processing settings in either tab. Closing without
saving discards pending changes. Previously applied changes stay in the main
draft; **Save settings** or **Run pipeline** persists them. Display settings do
not change stored masks. Standalone saves update the normal run settings.

Standalone launch: `uv run fisch-segtune /path/to/image-or-folder --tab compartment`.
