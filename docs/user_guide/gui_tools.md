# Preview and editing GUIs

[User guide](README.md)

This is a feature overview of the current tools: what you can select, adjust,
preview, or save. Controls can be unavailable when the image lacks the required
channels, frames, Z planes, or editable masks. Detailed procedures are linked
from each section; the interfaces are still being developed.

## Shared viewer controls

Most tools share these controls:

- **Source:** browse the experiment tree and open an image or mask. A tuner
  launched by the main GUI stays within that run; standalone tools allow
  choosing another experiments directory.
- **Navigation:** select the displayed image channel and move through available
  frames and Z planes. Zoom, pan, and return to the full-image view.
- **Image display:** switch between grayscale and channel colour, adjust the
  histogram/LUT intensity range, use **Auto-scale** or **Full range**, and edit
  colour-gradient markers. Display adjustments do not change stored intensities.
- **Mask display, where applicable:** show/hide the overlay and change opacity.
  Colour options depend on the tool: a label palette, solid/custom colours, or
  the binary-mask colour button.
- **Help:** open **Info** (`i`) for the searchable shortcut list. Drawing and
  selection gestures depend on the active tool/mode.

See [Image and mask viewers](viewers.md) for shared navigation, shortcuts,
overlays, cropping, and ImageJ metadata inspection.

| Shortcut / gesture | Action | Applies when |
| --- | --- | --- |
| Click **Info** (`i`) | Open searchable shortcut help. | Viewer active. |
| `←` / `→` or `A` / `D` | Previous / next frame. | Multiple frames available. |
| `↑` / `↓` or `W` / `Z` | Next / previous Z plane. | Multiple Z planes available. |
| `C` | Next active image channel. | BGTune skips excluded channels; ChannelReg cycles included comparison channels around a fixed reference. Other viewers retain their channel navigation. |
| `Ctrl` + scroll | Zoom in / out. | Cursor over the image. |
| `Ctrl` + left-drag | Pan the image. | Tracking viewer uses this gesture for rectangle selection instead. |
| `Home` | Return to the full-image view. | Image displayed. |
| `X` | Toggle the mask overlay. | Mask tools, including SegTune. |
| `V` | Compare original / preprocessed view. | Time registration, channel registration, and BGTune. |

Letter-key shortcuts apply when you are not typing into a text field.

## Time-registration preview GUI

Open **Frame-shift → Preview** or the **Time registration** tab in RegTune.

- Select a motion **Context**: linear, rotational, complex, or Custom.
- Choose/override **Algorithm** and **Method**. Available combinations depend
  on the algorithm; the resolved panel explains the effective plan.
- Select an optional **Fitting channel** and reference strategy:
  **previous**, **first**, or **mean**.
- Set **Overwrite existing pipeline output** for a subsequent pipeline run.
- Enable a **Fitting crop**; draw, move, resize, or enter its width/height,
  change the rectangle colour, and preview the crop. Fitting uses the crop;
  registration still applies to the full image.
- **Run preview** to fit the time sequence; **Cancel preview** while fitting.
  Inspect the selected frame/channel/Z plane as Original, Registered, or
  Composite overlay. Z fitting uses a maximum projection.
- **Save current settings** saves the active tab and keeps the window open;
  **Close window** closes without saving. If either used tab has unsaved settings
  or crop changes, choose to keep editing and save each tab, or close without saving. Settings can
  be saved without fitting a preview. Matching fitted transforms can be reused
  later by the pipeline.

| Shortcut | Action |
| --- | --- |
| `R` | Run preview, or cancel an active preview. |
| `V` | Switch between original and registered images (alignment composites in ChannelReg). |
| `S` | Save the current tab's settings; fitting a preview is optional. |

More: [Registration tuning](preprocessing.md#registration-tuning-and-accepted-transforms).

## Channel-registration preview GUI

Open **Channel-shift → Preview** or the **Channel registration** tab in RegTune.

- Select a **Context** for channel shift, dual-camera shift, complex shift,
  or Custom; choose/override **Algorithm** and **Method**.
- Select the **Reference channel** and a **Reference frame**. An unset reference
  defaults to the first channel; existing choices are preserved. Selecting a reference
  switches the display to it, while browsing display channels leaves the reference
  unchanged. Viewer frame numbering starts at 1.
- Select channels to **Exclude** from registration.
- Set the pipeline overwrite option and enable/adjust a **Fitting crop** as
  in time registration.
- **Run preview** to fit channels at the reference frame, or cancel fitting.
  Compare **Original alignment** with **Registered alignment** at the selected
  frame/Z. Both overlay the reference and the selected comparison channel, using
  consistent colours and contrast. The registered view transforms only the comparison
  channel. This tab previews channel registration directly on its input image.
- Press **C** to cycle included comparison channels while the reference stays
  fixed; with one comparison channel the view stays the same. Selecting the reference
  uses the first included comparison. Excluded channels remain selectable in the
  channel menu and are shown unchanged. **V** switches before/after for the same pair.
- **Save current settings** saves this tab and stays open. **Close window** warns
  about unsaved changes in either used tab before closing.

The [time-registration shortcut table](#time-registration-preview-gui) also
applies to this tab; `S` saves the active channel-registration settings.

More: [Registration comparison and saving](preprocessing.md#compare-the-registered-image).

## Background-subtraction preview GUI

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

| Shortcut / gesture | Action | Applies when |
| --- | --- | --- |
| `R` | Run preview on the displayed plane. | Image loaded. |
| `V` | Switch original / background-subtracted image. | Preview available. |
| Left-drag | Draw, move, or resize the measurement box. | Measurement box enabled. |
| `S` | Save current settings and stay open. | A preview is optional. |

More: [Background preview](preprocessing.md#background-subtraction-preview).

## Segmentation preview GUI

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
  the tuner open. **Close** checks for unsaved changes. Channel-entry deletion
  is applied immediately and is separate from other unsaved settings.

Preview masks do not replace the saved source segmentation artifact.

| Shortcut | Action |
| --- | --- |
| `R` | Run the segmentation preview. |
| `S` | Save current settings. |
| `X` | Show / hide preview masks. |

More: [Segmentation previews](segmentation.md#segmentation-and-compartment-previews).

## Compartment preview GUI

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

| Shortcut | Action |
| --- | --- |
| `S` | Save current compartment settings. |
| `X` | Show / hide preview masks. |

More: [Compartment measurements](analysis_and_results.md#quantification-and-compartments).

## Reference-mask GUI

Open the **Reference** tab in the drawing tool, or the pipeline's REF drawing mode.

- Choose the image/channel and the frame/Z plane on which to draw or edit.
- Select **Replace** or **Edit** drawing mode.
- Choose **Freehand polygon**, **Brush**, **Open line**, **Circle**, **Square**,
  or **Triangle**; adjust **Brush size**. Add with the left mouse button and
  erase with the right button. Move an existing region using the shared
  Shift-selection/drag controls.
- **Undo**, **Clear current** plane, or **Clear all** planes for the selected
  mask channel. These session changes reach the saved file only when saved.
- Enable **Propagate drawings**, choose available **Time** or **Z** axis,
  and choose **Extend to first plane** and/or **Extend to last plane**.
- Toggle **Live preview** to inspect propagation without replacing the drawings.
- Show/hide the mask, adjust opacity, and change its display colour.
- Enter a **File label** and **Save mask** as `proc_ref_<label>.tif`.
  Open saved masks from the browser/tree to inspect or continue editing them.

| Shortcut / gesture | Action | Scope |
| --- | --- | --- |
| Left-click / drag | Draw or add with the selected tool. | Current plane and drawing mode. |
| Right-click / drag | Erase with the selected tool. | Current plane and drawing mode. |
| `Shift` + left-drag | Select and move a connected mask region. | Region under the cursor. |
| `Ctrl+Z` | Undo the latest edit. | Current plane. |
| `Ctrl+D` | Clear current. | Current plane, in the session. |
| `Ctrl+Shift+D` | Clear all. | Selected mask channel, all frames and Z planes, in the session. |
| `S` | Save mask. | Current mask; clearing alone does not change the saved file. |

More: [Reference and ROI workflow](reference_and_roi_masks.md).

## ROI-mask GUI

Open the **ROI** tab in the drawing tool, or the pipeline's ROI drawing mode.

- Choose the displayed image/channel and frame/Z plane. The ROI defines included
  pixels for distance-profile analysis.
- Use the same drawing shapes, brush-size control, left-add/right-erase gestures,
  region movement, Undo, and clearing actions as the reference tool. ROI manual
  drawing uses Edit mode rather than exposing the Replace/Edit selector.
- Inspect the intensity histogram and adjust the current plane's **Minimum**
  and **Maximum** threshold, by entering values or moving the threshold range.
- Apply **Automatic threshold** to the **Current plane** or the **Stack**.
- Enter a **Manual range** and **Apply to stack**.
- Use stack cleanup for the selected channel: **Fill holes**, or set a minimum
  area and **Remove small objects**. Hole filling preserves manually erased pixels.
- Propagate drawings along Time/Z where available, extend to either endpoint,
  and toggle **Live preview**. Adjust mask colour, visibility, and opacity.
- Set a **File label** and **Save mask** as `proc_roi_<label>.tif`.

The [reference-mask shortcut table](#reference-mask-gui) also applies to ROI
drawing. ROI uses Edit mode for manual drawing.

More: [Drawing and navigation](reference_and_roi_masks.md#drawing-and-navigation).

## Tracking viewer GUI

Open **Image / Mask Viewer** with a tracking artifact. The available tools
depend on the loaded artifact; tracking-specific controls are not used for an
ordinary image or REF/ROI mask.

- Choose the displayed image channel, mask channel, frame, and Z plane. Show
  or hide the raw image and mask overlay; adjust overlay colour/opacity.
- Select cells by clicking, entering comma-separated IDs, or drawing the viewer's
  selection rectangle. Inspect the selected IDs and **Clear selection**.
- Display cell IDs for **None**, **Selected**, or **All** cells.
- Show/hide track paths, display **all** or **selected** paths, choose path
  thickness, and show the full path or build it only to the current frame.
- Show/hide centroid markers, set their size, and use track-palette or single
  colours for the trajectory display.
- Filter by track length: less/greater than, inclusive comparisons, equal,
  not equal, or an inclusive range. **Filter** applies the values;
  **Clear filter** removes the filter.
- Enable **Crop**, draw/move/resize a rectangle or enter its dimensions, change
  its colour, use **Crop** to fit selected cells across time, and **Preview**
  to zoom to it.
- Give an optional export label and **Save current display** to a new TIFF
  with image data and ImageJ overlays, using the active crop when enabled.

| Shortcut / gesture | Action | Applies when |
| --- | --- | --- |
| `Ctrl` + left-click on a mask or centroid | Select / unselect a cell. | Selection enabled. |
| `Ctrl` + left-drag | Select cells with centroids inside a rectangle. | Viewer selection; with crop enabled, also sets the crop rectangle. |
| `Enter` in the cell-ID field | Apply the entered IDs. | Comma-separated IDs allowed. |
| Left-drag | Draw, move, or resize the crop rectangle. | Crop enabled. |
| `Home` | Return to the full-image view. | Crop remains enabled for export if selected. |

More: [Viewer selection and exports](viewers.md#drawing-selection-and-keyboard-shortcuts).

## Tracking editor GUI

Enable **Edit tracking** in the pipeline, or open `fisch-trackedit` independently.

- Navigate image/mask channels, frames, and Z; use the tracking display and
  length-filter controls to inspect the result. Select up to two tracks for
  editing operations; the viewer's unlimited multi-selection is not used here.
- **Merge Tracks** or **Link histories** for selected tracks.
- **Split Track** from a frame, or **Unlink entire track**.
- **Split Mask** using a local preview; inspect and **Accept split** or
  **Cancel split** before changing the result.
- Enable **Add / edit masks mode**. Supply positive/negative prompts for local
  µSAM prediction, adjust expected cell diameter, and inspect the proposal.
- Correct masks using manual brush/enclosed filling, adjust brush size, and
  change the active/other-mask editing colours.
- **Accept mask**, **Cancel current mask**, **Delete current mask**, or
  **Delete current track**; use Undo for supported edits.
- **Save edited tracking** writes the edited result, including active
  track-length filtering where applicable. In the pipeline, **Use original
  tracking** finishes without adopting an edited result.

| Shortcut / gesture | Action | Applies when |
| --- | --- | --- |
| `Ctrl` + left-click on a mask or centroid | Select / unselect a track. | Up to two selected tracks. |
| `Ctrl` + left-drag | Pan the image. | Editor active. |
| `Enter` in the cell-ID field | Apply the entered ID. | Single-ID entry. |
| Left-click / right-click | Add positive / negative prediction prompts. | Add / edit masks mode. |
| Left-drag / right-drag | Brush / erase. | Add / edit masks mode. |
| Left-click / drag | Mark a division inside the selected mask. | Split Mask mode. |
| `S` | Accept a ready mask or split preview in the session. | Does not replace **Save edited tracking**. |
| `Ctrl+Z` | Undo the latest supported edit or preview. | Editing. |
| `Ctrl+D` | Delete the selected track's current mask. | Current frame. |
| `Ctrl+Shift+D` | Delete the selected track across frames. | Current mask channel and Z plane. |

The crop/export panel belongs to the viewer rather than the editor. Rerun
measurements after accepting different masks. More:
[Editing and saving tracking](tracking.md#editing-and-saving-tracking-results).

## Pipeline drawing-session controls

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

More: [Collection and experiment navigation](reference_and_roi_masks.md#collection-panel-preview-and-experiment-navigation).
