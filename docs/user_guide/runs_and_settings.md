# Runs, channels, and settings

[User guide](README.md) · [Previous: Your first analysis](first_analysis.md) ·
[Next: Preprocessing](preprocessing.md)

A run is the project folder you open in FIScH. It contains original acquisitions, their series, saved settings, and results. Choose or reopen the run first, then configure the steps you want to run.

## Open a run

Select a run directory with Browse, enter a path and press Enter, or drag one
local folder onto the main window or Run directory field. Folder selection loads
that run's saved settings, or fresh template settings if none exist. Folder
changes are blocked while the pipeline runs.

## Convert and navigate the processing pages

Open the dedicated [Convert settings](settings/convert.md) page for source labels, exported channels, projection, and Next/Back behaviour.

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
`.pipeline/settings.toml` in the run directory before processing starts. This also
applies when running `pipeline.py` with the packaged `user_settings.toml`,
so the GUI can later load the run's settings. The saved copy reflects the
latest launch and remains available if processing fails.

In the GUI, **Save settings** saves the current draft into the selected run without
starting processing. Changed snapshots are retained in `.pipeline/settings_history/`
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
`.acquisition/experiment_state/<series>/` directory. Artifact paths, rather than a second
workflow manifest, are the durable evidence used to resume work. Conversion can
split a raw file into several experiment branches. Re-running an unchanged step
reuses completed output. FIScH keeps each preprocessing result independently:

| Step | Output |
| --- | --- |
| Convert | `proc_array_raw.tif` |
| Channel-shift | `proc_array_reg_channel.tif` |
| Frame-shift | `proc_array_reg.tif` |
| Background subtraction | `proc_array_bgsub.tif` |
| Segmentation | `proc_masks_seg.tif` |
| Tracking | `proc_masks_track.tif` |

For folder movement and hidden metadata, see [Portable projects](portable_projects.md).

## Exclude experiments after conversion

Select one or more folders in the run browser and press **Exclude exps.**
An acquisition or condition folder covers all converted series beneath it;
overlapping selections count each experiment once. The action button sits beside
the browser's **Selected** path display.

When every selected experiment is excluded, the button becomes **Re-include
exps.** A mixed selection offers **Exclude exps.**, making the
whole selection excluded. The action is disabled without a converted-folder
selection and while the pipeline runs.

**Exclude others**, beside this button, activates the selected experiments and
excludes every other converted experiment in the run. This lets you overwrite
only the selected experiments using the normal pipeline controls. The inclusion
choices persist until you change them. Both actions require converted experiments;
fully rebuild migrated checkpoints before changing their inclusion.

When all experiments outside the selection are excluded, the second button becomes
**Re-include others**, bringing them back into processing and analysis. A mixed
set of other experiments offers **Exclude others**. Re-including others leaves
the selected experiments' inclusion unchanged. The button is disabled when
the selection already covers every converted experiment. Both buttons use a
smaller font and update their labels to show the next action.

For multiple selections, the display summarizes the selected folders and covered
experiments. A single selection shows its path. Long text wraps and takes space
from the browser tree; the tool buttons remain on the row below.

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
outputs also need work). FIScH regenerates master tables from valid active-series
results and schedules missing or outdated measurements first. Individual results
are preserved. With no active results, rebuilding removes the old master tables.
Outdated files appear amber in the browser, including master Parquets and
downstream results invalidated by rerunning an upstream step. Their normal
appearance returns after rebuilding or updating resolves the checker warning.

## Renaming existing channel labels

Use [Manage files → Channel labels](channels_and_labels.md#rename-channels-in-an-existing-run) to rename saved channel references consistently. The same operation can be inspected or previewed from the command line; `--apply` is required to write:

```bash
uv run fisch channel-labels /path/to/run
uv run fisch channel-labels /path/to/run --set 0=Green --set 1=Red
uv run fisch channel-labels /path/to/run --set 0=Green --set 1=Red --apply
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

## Stop run and Quit

**Stop run** interrupts the active pipeline and keeps the main GUI open. It is
disabled when no run is active. A confirmation explains that restarting may
require enabling **Overwrite** for affected steps. The GUI remains available
for adjusting settings and starting another run.

**Quit** closes FIScH normally when idle. During a run, Quit and the window's
**X** ask before terminating processing and closing the application. **No** is
green and selected by default; **Yes** is red. Unsaved GUI edits are lost on
force quit. An intentional quit does not trigger installation repair or a
second relaunch dialog. Real installation/update problems still use startup repair.

## Launching individual image tools

Launch the main settings interface with `uv run fisch-gui`, or open the image
tools directly:

```bash
uv run fisch-segtune
uv run fisch-drawmask
uv run fisch-regtune
uv run fisch-trackviewer --experiments-dir /path/to/run
uv run fisch-trackedit /path/to/experiment/proc_masks_track.tif
uv run fisch-channel-labels /path/to/run
```

## Command-line processing

The command-line interface is available through `uv run fisch --help`. Running
`uv run fisch run path/to/settings.toml` launches the same Ref/ROI collection
window when the configured analyses request interactive masks. Calling
`start_pipeline()` directly stays noninteractive unless a mask interaction
bridge is supplied.

## Help inside the GUI

Click the **ⓘ** button to open **User guide** and **Shortcuts** in a separate
help window. The guide starts at the page for the tab or tool you were using;
subsequent application tab changes do not move it. Settings tabs without a
dedicated guide page open the guide home page; preview-tool guides are opened
from the preview windows themselves. Follow links or use **Back**,
**Forward**, and **Home** to browse the full guide offline. Search lists matching guide pages, with exact titles and title words before
body-text matches. Press Enter or select a result to open it. **Find in page**
uses the same query within the page currently displayed. External web links open in your web browser.

When a tool has shortcuts, help opens on **Shortcuts** first. Only its relevant
shortcuts are displayed; expand **Other shortcuts** to inspect the rest of the
catalog. The search field filters both tables. Interfaces without shortcuts,
such as the main GUI and Manage files, open on **User guide**.

The browser's title row has a **Full Report** button. **Extra tools**
groups the File Viewer and tracking editor below the browser.
