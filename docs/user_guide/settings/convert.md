# Convert

[Guide home](../README.md)

Related: [Main GUI](../runs_and_settings.md) · [Channels and labels](../channels_and_labels.md) · [Shared settings](common.md) · [Manage files](../tools/manage_files.md)

Convert source ND2/TIFF images into the managed FIScH images used by later steps.

## Inputs and controls

| Setting / action | Practical meaning |
| --- | --- |
| Channel / Expected colour / Label | Enter optional labels in source order. Blank cells use detected/default names; colours come from acquisition metadata where available. |
| Export channels | Keep the channels needed downstream; multiple selection is allowed. |
| Z projection | Max, mean, sum, or standard deviation combines Z planes. None preserves the Z stack. |
| Compression | TIFF storage compression; this is separate from image processing. |
| Edit labels… | Opens Manage files to rename labels in already converted files. Editing the Convert table alone configures the next conversion. |

## Convert and navigate the processing pages

The main interface has two pages. An unconverted run opens on **Convert**;
**Next** performs conversion only and moves to the processing page after it
finishes successfully. Reopening a run containing converted FIScH images opens the
processing page directly, with **Preprocess** selected. **Back** returns to
Convert. An unchanged **Next** returns to processing without another conversion;
changed conversion settings, including overwrite, request a fresh conversion.

Before conversion, check source channel order, the chosen/default labels, and which channels to export. See [Channels and labels](../channels_and_labels.md) for count warnings, generic fallback names, and the choices offered downstream.

Files with the same stem in the same folder receive extension-specific
acquisition folders (for example, `sample_nd2/sample.nd2` and
`sample_tif/sample.tif`), with a console log message and no popup. Original
filenames are preserved. Matching stems in different subfolders do not need
this adjustment. Existing or conflicting destination folders block conversion.

Settings changed while conversion is running apply to the next conversion.

## Output

Conversion writes `proc_array_raw.tif` for each series and records completed
artifacts in experiment state. See Shared processing settings for Include,
Overwrite, Execution and Workers.
