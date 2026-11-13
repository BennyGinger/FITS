# Channels and labels

[Guide home](README.md)

Related: [Convert](settings/convert.md) · [Channel labels editor](tools/channel_labels.md) · [Output tables](output_tables.md)

Channel names connect conversion, registration, segmentation, tracking, and
measurement tables. Choose them in **source channel order** before conversion.
To rename channels in existing results, use **Manage files → Channel labels** so the
supported files and settings stay consistent.

## What does “label” mean?

| Term | Example | Meaning |
| --- | --- | --- |
| Channel label/name | `GFP`, `RFP`, `nuclei`, `C_1` | Name assigned to an image or mask channel. It identifies a channel, not a particular cell. |
| Object/mask label | `7`, `24` | Nonzero integer stored in a segmentation/tracking mask to identify an object. Label 0 is background. |
| Reference/ROI name | `edge`, `region` | Name of a saved drawing, such as `proc_ref_edge.tif` or `proc_roi_region.tif`. A named drawing can contain one or more channels. |
| Cell identifier | `cell_id` in a table | Identifier built from experiment, object type, object channel, and numeric object label; segmentation IDs also include the frame. |

The **Manage files → Channel labels** tool renames channel names. Numeric object labels in
mask pixels and reference/ROI drawing names are separate concepts.

## Choose source channel names

In **Convert → Channel labels**, enter one name for **every channel in the
original acquisition**, in exactly the original order. Names can be freely
chosen; they do not have to be a particular fluorophore or match the microscope's
channel names. Use clear, distinct names consistently across the run.

For a three-channel acquisition ordered as green, red, then nuclear signal:

```text
GFP, RFP, DAPI
```

Here the first source channel becomes GFP, the second RFP, and the third DAPI.
Entering `RFP, GFP, DAPI` would give different names to the same channel data;
FIScH does not infer or correct their biological identity from the names.

The channel count alone cannot detect an incorrectly ordered list. Check the
acquisition or view its channels if you are unsure. Names used by later settings
must match the saved names, including case: `GFP` and `gfp` are different names.

Channel names must be unique. The rename tool additionally requires non-empty
names and trims surrounding whitespace. Enter labels in the conversion table,
one source channel per row.

## Expected channel count and generic fallback names

The conversion table has one row per detected source channel, before
exported-channel selection. A wrong number of names
produces an orange warning listing the expected count, entered count, and
generic names conversion will use if the mismatch is left unresolved.

The conversion table lists **Channel**, **Expected color**, and **Label**.
Colors come from stored NIS `uiColor` metadata or ImageJ TIFF LUTs, with a colored dot and the exact
RGB hex value in its tooltip. Missing, invalid, or conflicting colors show
`nan`. When acquisitions disagree, only colors shared by every input are used
for default labels. The label cells remain empty until you fill them; their
tooltips show the fallback names. Blank entries use color names such as
`green`, with repeated colors numbered `green_1`, `green_2`; unavailable colors
use `C1`, `C2`, etc. Colors are display hints, not fluorophore identification.

User labels always determine converted-file LUTs. For example, labeling a
source green channel `RFP` gives the converted channel a red LUT. The original
ND2 display color remains green in the reader metadata exposed for raw viewing.

The status panel also shows **Frames** for all input experiments, read from
acquisition headers. Equal lengths show the exact count; mixed lengths show
**≥** followed by the minimum. If any experiment has only one frame, enabling
Tracking or Frame-shift registration produces an orange console warning.
Starting the pipeline with either incompatible step enabled is blocked with a
red console error. Disable those steps to quantify single-frame segmentation
masks directly. Channel-shift registration cannot be enabled when only one
image channel is available, including when only one channel is selected for
export. An incompatible step loaded from settings can still be unticked.

Missing required settings, such as the user name, are reported in red in the
console with an attention icon instead of opening a warning dialog.

For a three-channel source:

| Supplied names | Count | Conversion result |
| --- | --- | --- |
| `GFP, RFP, DAPI` | 3 | Names are used in that order. |
| `GFP, RFP` | 2 | Warning; all names become `C1, C2, C3`. |
| `GFP, RFP, DAPI, brightfield` | 4 | Warning; all names become `C1, C2, C3`. |
| No labels supplied to conversion | 0 | Source color names, then generic names `C1, C2, C3`. |
| `GFP, "", DAPI` | 3 | The blank second label uses its color, or `C2`. |

On a count mismatch, fallback replaces the **whole naming list**. It does not identify fluorophores
or change the pixel values. Duplicate names are a separate validation error,
not a supported way to trigger fallback.

In the main GUI, leave label cells blank to use defaults. If you want
generic names deliberately, enter `C1, C2, …` for all source channels. This
keeps the exported-channel choices and later settings aligned with the names
that conversion will actually save.

If fallback has occurred, downstream selections must use the resulting names.
For example, a request to export only `GFP` cannot match a source that conversion
has renamed to `C1, C2, C3`. Correct the labels/selections before processing,
or rename existing converted results using the tool described below.

### A different error: mixed source channel counts

A run may contain supported raw ND2 and TIFF acquisitions, but their **numbers
of source channels must agree**. A mixture of two-channel and three-channel
files produces a red, blocking input error. Naming fallback cannot fix that
mismatch; put acquisitions with different source counts in separate runs.
The console lists the affected filenames and their channel counts, with guidance
to split them into separate run directories. The settings panel does not repeat
this warning; the red status indicator and blocked conversion remain visible.

## Exported channels and downstream choices

**Exported channels** selects which of the source channels are converted and
saved in the FIScH raw image. All listed channels are selected by default;
multiple selection is allowed. You must still label all source channels even
when exporting only a subset.

For a source labeled `GFP, RFP, DAPI`, exporting only `RFP, DAPI` saves those two
channels. GFP will not be available for later processing of that converted image.
Naming the channels is separate from selecting which channels to save.

| Setting | Channels offered / selection behavior |
| --- | --- |
| Channel-registration reference | Exported image channels; one required selection. An empty starting choice means it has not been selected. |
| Time-registration fit channel | Exported image channels; one optional selection, with `None` available. |
| Registration/background exclusions | Exported image channels; multiple selection. `None` means no channels are excluded and is exclusive of actual channel selections. |
| Channel to segment | Exported image channels; one per segmentation section. Use **+ / −** to add/remove sections. |
| Nuclear channel | Exported image channels; one optional selection, with `None` available. |
| Channels to track | Channels configured as segmentation targets, rather than every exported image channel. Multiple selection is allowed. |

Multi-selection controls display the selected names on one line, with an
ellipsis if needed. Click to open the checked choices; click outside or press
Escape to close. Hovering shows the complete selection and parameter help.

FIScH records original source channel indices so a subset still refers to the
correct original channels. The GUI table numbers channels from **1**. The
command-line rename tool uses source indices starting at **0**, so `--set 0=GFP`
renames the first source channel. A subset need not start at the first source
channel or have consecutive indices.

## Rename channels in an existing run

Changing the Convert naming list prepares conversion settings; it does not
perform the run-wide rename of existing saved results. For an existing analysis:

1. Open its run folder and finish/stop any running processing.
2. Open **Manage files** and find **Channel labels**. You can also use
   **Edit labels…** in Convert to open the same manager. FIScH inspects its
   managed files and displays labels beside their channel numbers and expected colours.
3. Enter the new, unique, non-empty name for each displayed source channel.
   This changes names, not the channel order or which signal a channel contains.
4. Review the file list. It previews files that reference a name you changed;
   files unrelated to the changed channels are omitted.
5. Click **Save new labels**, confirm the proposed renames, and wait for
   completion. Use **Rescan** for a fresh inspection before saving again.
6. Check the updated channel choices and measurement tables.

The button is disabled during pipeline processing. Older read-only artifacts
need the appropriate migration before they can be modified.

### Which files does the rename cover?

For the opened run, the tool inspects supported active FIScH files and updates
known references to the changed source channels:

- Managed FIScH TIFF image/mask channel metadata, supported overlay exports,
  and relevant channel references in embedded workflow metadata.
- Quantification channel columns: `object_channel`, `intensity_channel`, and
  `ref_channel`, in experiment and master tables.
- Distance-profile channel columns: `channel`, `ref_channel`, and `roi_channel`,
  in experiment and master tables.
- Saved run settings and experiment-state channel references.

Image/mask pixel values, numeric object labels, overlay geometry, and measured
numeric values are preserved. Files can be rewritten to publish the updated
labels; this does not rerun the image-processing algorithms.

**Renaming an object channel also updates quantification `cell_id` strings**
because the object-channel name is part of cell identity. Renaming only an
intensity channel leaves `cell_id` unchanged. Keep this in mind if external
tables or scripts join results using old cell IDs.

The operation covers known FIScH files in the opened run. It does not rename
raw acquisition filenames, reference/ROI drawing names, retained backup copies,
external protocols, or references in your own notebooks and spreadsheets.
Update separately maintained copies and scripts as needed.

### Why might FIScH refuse a rename?

- One source index has different existing names in different files.
- One existing name maps to different source indices.
- Files lack sufficient channel-index metadata to establish identity safely.
- Saved run settings or state conflict with the recorded TIFF labels.
- A file changed after inspection, or another process is writing the run.
- A proposed name is empty or duplicates another channel name.

The error identifies the inconsistency. Use **Rescan** for changed files and
resolve identity conflicts before retrying; the tool does not guess which
signal a channel represents.

## Channel names in the output dataframes

`object_channel` identifies the mask channel; `intensity_channel` identifies
the measured image channel. They can differ. In a distance-profile table,
the measured image channel is instead called `channel`. `ref_channel` and
`roi_channel` identify channels inside the corresponding drawings, while
`ref_label_name` and `roi_label_name` name those drawings.

See [Understanding the output tables](output_tables.md) for the full column
reference and [Analysis identifiers](analysis_identifiers.md) for cell-ID details.
Channel names can also appear in a TIFF's
[ImageJ/Fiji metadata summary](viewers.md#inspecting-artifact-metadata-in-imagejfiji).

## Implementation references

- [Channel selection and fallback names](../../scope_io/src/scope_io/metadata/resolve.py).
- [Shared raw-input checks](../../src/fisch/workflows/checks/raw_inputs.py).
- [Run inspection and name validation](../../src/fisch/channel_labels/discovery.py).
- [Settings/table channel mappings](../../src/fisch/channel_labels/documents.py).
- [Rename application](../../src/fisch/channel_labels/apply.py) and
  [GUI controls](../../src/fisch/gui/channel_labels/window.py).
