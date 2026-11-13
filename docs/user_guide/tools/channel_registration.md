# Channel-registration preview

[Guide home](../README.md)

Related: [Preprocessing overview](../preprocessing.md) · [Fitting and saving](registration_controls.md) · [Settings](../settings/channel_registration.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

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

Open **Info → Shortcuts** for the applicable keys. For example, `S` saves the
active channel-registration settings.
