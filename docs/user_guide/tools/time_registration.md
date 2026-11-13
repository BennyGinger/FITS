# Time-registration preview

[Guide home](../README.md)

Related: [Preprocessing overview](../preprocessing.md) · [Fitting and saving](registration_controls.md) · [Settings](../settings/time_registration.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

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
