# ROI-mask editor

[Guide home](../README.md)

Related: [Reference editor](reference_masks.md) · [Drawing workflow](../reference_and_roi_masks.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

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

ROI uses Edit mode for manual drawing. Open **Info → Shortcuts** for the
applicable drawing and navigation keys.
