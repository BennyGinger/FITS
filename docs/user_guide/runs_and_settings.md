# Runs, channels, and settings

[User guide](README.md) · [Previous: Your first analysis](first_analysis.md) ·
[Next: Preprocessing](preprocessing.md)

A run is the project folder you open in FITS. It contains original acquisitions, their series, saved settings, and results. Choose or reopen the run first, then configure the steps you want to run.

## Open a run

Select a run directory with Browse, enter a path and press Enter, or drag one
local folder onto the main window or Run directory field. Folder selection loads
that run's saved settings, or fresh template settings if none exist. Folder
changes are blocked while the pipeline runs.

## Convert and navigate the processing pages

The main interface has two pages. An unconverted run opens on **Convert**;
**Next** performs conversion only and moves to the processing page after it
finishes successfully. Reopening a run containing converted FITS images opens the
processing page directly, with **Preprocess** selected. **Back** returns to
Convert. An unchanged **Next** returns to processing without another conversion;
changed conversion settings, including overwrite, request a fresh conversion.

Before conversion, label every source channel in source order and choose which channels to export. See [Channels and labels](channels_and_labels.md) for count warnings, generic fallback names, and the choices offered downstream.

Files with the same stem in the same folder receive extension-specific
acquisition folders (for example, `sample_nd2/sample.nd2` and
`sample_tif/sample.tif`), with a console log message and no popup. Original
filenames are preserved. Matching stems in different subfolders do not need
this adjustment. Existing or conflicting destination folders block conversion.

## Processing tabs and required settings

The processing page has **Preprocess**, **Process**, and **Analysis** tabs,
each with smaller step subtabs across the top. **Frame-shift** and
**Channel-shift** are the time and channel registration settings. There is no
separate pipeline-step panel. Each step's **Enable** checkbox includes or omits
that step; its settings sit inside the Enable group. **Advanced settings** and
advanced runtime settings collapse fully, letting the tab's scroll area adjust
instead of reserving empty space.

**Run pipeline** launches the normal pipeline with the configured enabled steps
and overwrite rules, including Convert when enabled. The page layout does not
change the workflow's execution order or processing algorithms.

For enabled steps, the GUI requires conversion channel labels, a channel-
registration reference channel, at least one segmentation channel, and at
least one tracking channel. If one is missing, the GUI keeps the affected step
or phase selected and explains which field must be completed. **Run pipeline**
remains disabled until all required fields belonging to enabled steps have a
value. **Next** checks the Convert inputs independently of later steps, so
unfinished processing settings do not prevent conversion. These checks detect
omitted input only; the pipeline continues to handle
invalid channel names and other data-dependent validation.

## Saving settings and protocols

Every launch saves the input configuration, including its comments, as
`.fits/fits_settings.toml` in the run directory before processing starts. This also
applies when running `pipeline.py` with the packaged `user_settings.toml`,
so the GUI can later load the run's settings. The saved copy reflects the
latest launch and remains available if processing fails.

In the GUI, **Save settings** saves the current draft into the selected run without
starting processing. Changed snapshots are retained in `.fits/settings_history/`
before replacement. **Save protocol** exports a reusable TOML file, and **Load
protocol** validates it and asks before replacing the current GUI settings.
Both protocol actions require a selected run and are disabled during processing.
Protocols retain channel order, per-channel segmentation settings and custom model
paths, while preserving the current run directory, user name and log destination
on load. All protocol overwrite flags are reset to false. Loading does not save
the run settings or change results; use Save settings or Run to persist the draft.
Changed processing parameters can flag existing results and their dependents for the [rebuild/continue decision](reprocessing_and_file_management.md).

## Experiment state and saved outputs

Each series has an `experiment_state.json` file containing its artifacts,
completed steps, metadata, and provenance, stored inside its acquisition's
`.fits_experiment/experiment_state/<series>/` directory. Artifact paths, rather than a second
workflow manifest, are the durable evidence used to resume work. Conversion can
split a raw file into several experiment branches. Re-running an unchanged step
reuses completed output. FITS 4 keeps each preprocessing result independently:

| Step | Output |
| --- | --- |
| Convert | `fits_array_raw.tif` |
| Channel-shift | `fits_array_reg_channel.tif` |
| Frame-shift | `fits_array_reg.tif` |
| Background subtraction | `fits_array_bgsub.tif` |
| Segmentation | `fits_masks_seg.tif` |
| Tracking | `fits_masks_track.tif` |

For folder movement and hidden metadata, see [Portable projects](portable_projects.md).

## Exclude experiments after conversion

Select one or more folders in the run browser and press **Exclude experiments**.
An acquisition or condition folder covers all converted series beneath it;
overlapping selections count each experiment once. The action button sits beside
the browser's **Selected** path display.

When every selected experiment is excluded, the button becomes **Re-include
experiments**. A mixed selection offers **Exclude experiments**, making the
whole selection excluded. The action is disabled without a converted-folder
selection and while the pipeline runs.

Excluded series have muted text and a gray circle-minus folder badge. Parents
with some excluded series have an amber half-circle badge; parents with all
series excluded have the gray badge. Tooltips explain the state or show excluded
counts. Files remain available for inspection.

Exclusion applies to all pipeline processing and analysis, including batch,
conveyor and interactive runs. The saved `excluded` flag survives rebuilding;
conversion does not overwrite excluded siblings. Missing flags in older states
mean active. Metadata-only legacy migration keeps experiments active; fully
rebuild migrated checkpoints before changing their inclusion.

Changing inclusion makes existing combined analysis outdated. Use **Manage
files → Rebuild analysis…** (or the required-results rebuild when individual
outputs also need work). FITS regenerates master tables from valid active-series
results and schedules missing or outdated measurements first. Individual results
are preserved. With no active results, rebuilding removes the old master tables.
Outdated files appear amber in the browser, including master Parquets and
downstream results invalidated by rerunning an upstream step. Their normal
appearance returns after rebuilding or updating resolves the checker warning.

## Renaming existing channel labels

Use [Edit Channel Labels](channels_and_labels.md#rename-channels-in-an-existing-run) to rename saved channel references consistently. The same operation can be inspected or previewed from the command line; `--apply` is required to write:

```bash
uv run fits channel-labels /path/to/run
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red
uv run fits channel-labels /path/to/run --set 0=Green --set 1=Red --apply
```

## Activity display

The **Activity log** header always shows a step label, progress bar, and elapsed
time. Batch runs mirror the current step's terminal counter; conveyor runs show
**Pipeline steps**, using the terminal Pipeline counter, including totals added
by output branches.
Conversion-only runs show **Convert**. Interactive runs show overall configured
stage completion as **Pipeline steps**. The elapsed clock has no time-remaining
estimate and freezes when work finishes; the blue activity indicator runs while
the pipeline is active.

## Launching individual image tools

Launch the main settings interface with `uv run fits-gui`, or open the image
tools directly:

```bash
uv run fits-segtune
uv run fits-drawmask
uv run fits-regtune
uv run fits-trackviewer --experiments-dir /path/to/run
uv run fits-trackedit /path/to/experiment/fits_masks_track.tif
uv run fits-channel-labels /path/to/run
```

## Command-line processing

The command-line interface is available through `uv run fits --help`. Running
`uv run fits run path/to/settings.toml` launches the same Ref/ROI collection
window when the configured analyses request interactive masks. Calling
`start_pipeline()` directly stays noninteractive unless a mask interaction
bridge is supplied.
