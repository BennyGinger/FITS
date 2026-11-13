# Frame-shift

[Guide home](../README.md)

Related: [Preprocessing](../preprocessing.md) · [Time-registration preview](../tools/time_registration.md) · [Shared settings](common.md) · [REF/ROI alignment](../reference_and_roi_masks.md)

Correct drift between frames. Open **Preprocess → Frame-shift** in the main GUI.
Enable it when the same structures move through the image because of acquisition drift.

## Settings

| Parameter | Practical meaning |
| --- | --- |
| Context | Linear drift corrects translation; rotational drift handles rotation; complex drift allows a more flexible transform. The context selects the algorithm/method preset. |
| Reference strategy | Previous compares consecutive frames; first uses the initial frame; mean uses an average reference. |
| Fitting channel (optional) | Choose a stable exported signal for estimating motion, or leave None for algorithm-selected fitting. |
| Algorithm / Method (advanced) | Override the preset when needed. Available combinations depend on the algorithm. |
| Preview | Open the time-registration preview to compare alignment and optionally choose a fitting crop. |

Registration changes geometry. Check saved REF/ROI drawings after changing it.
Fitting on Z stacks uses a maximum projection and applies the resulting 2D
transforms to the Z planes. A fitting crop does not crop the output image.

## Output

Writes `proc_array_reg.tif`. Channel registration, when included, precedes time
registration. Saving a preview changes the main draft; run the pipeline to
produce the registered stack.
