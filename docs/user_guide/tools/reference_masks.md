# Reference-mask editor

[Guide home](../README.md)

Related: [ROI editor](roi_masks.md) · [Drawing workflow](../reference_and_roi_masks.md) · [All tools](../gui_tools.md) · [Viewer controls](viewer_controls.md)

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
