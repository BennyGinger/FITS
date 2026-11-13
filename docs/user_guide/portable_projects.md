# Moving a project: what is portable?

[Guide home](README.md)

Related: [Manage files](tools/manage_files.md) · [File-management overview](reprocessing_and_file_management.md) · [Backups](tools/backups.md)

**A complete FIScH run/project can be moved or copied to another folder, disk,
or computer.** Keep its contents and internal structure together, including
the hidden metadata folders. Open the project at its new location in FIScH and
use **Manage files → Update paths and condition tags…** if FIScH reports that
saved location information needs refreshing.

That action updates location information and master-table grouping. **Moving
a project does not itself require reprocessing its images or remeasuring cells.**

## The two folder units

A **run** is the project folder you open in FIScH. Its `.pipeline/` directory holds
run settings, logs, reports, and run-level backups. FIScH recognizes the run by
`.pipeline/settings.toml` or `.pipeline/logs/`.

An **acquisition** groups one original image file with all of its series and
their shared `.acquisition/` metadata. For example:

```text
my_project/                         ← move this whole folder for a complete project
  .pipeline/                            ← keep, including saved settings
  master_quantification.parquet
  master_distance_profile.parquet
  control/                          ← optional condition folder
    sample/                         ← complete acquisition: move this as one unit
      sample.nd2                    ← original acquisition
      sample_s1/                    ← series 1 images, masks, and measurements
      sample_s2/                    ← series 2, if present
      .acquisition/             ← shared state, tuning, caches, and backups
        experiment_state/
        tuning/
        cache/
        backup/
```

Not every project has every table, series, or optional metadata subfolder.
Hidden folders are part of the project even when your file browser hides them.

## What can I move or copy?

| Item | Supported use | What must stay together / what to do afterward |
| --- | --- | --- |
| **Whole project/run folder** | Move, copy, or rename it, including transfer to another computer. | Keep everything inside it. Open the new project location and refresh paths/tags if requested. FIScH must be installed on the destination computer. |
| **Whole condition folder** | Move or rename it within the run, or transfer its complete acquisitions to another recognized FIScH run. | Keep each acquisition intact. Refresh the destination run's paths/tags; folder-based conditions and master IDs may change. |
| **Whole acquisition folder** such as `sample/` | Move it within a run or into another recognized FIScH run. | Include the original image, every series, and `.acquisition/`. Open the containing run and refresh paths/tags. Avoid destination-name collisions; do not merge folders by overwriting existing files. |
| **An individual TIFF or Parquet result** | Copy it elsewhere to inspect, share, or analyze independently. | This is a result export, not a resumable FIScH project. Copying one output does not carry its original acquisition, processing state, tuning, or related files. |
| **A compacted project/acquisition** | Move or copy it as a complete unit. | Compaction intentionally removes intermediates. Retained results remain usable; later upstream reprocessing can require rebuilding the missing stages from the original acquisition. |

An acquisition is portable **within the context of a run**. A processed
acquisition placed alone in an otherwise empty folder is not automatically a
new project: without a recognized containing run, FIScH reports it as detached.
To transfer a complete analysis without arranging a destination run, transfer
the whole project folder.

Moving only an acquisition does not bring the original run's settings, master
tables, logs, or run-level backups from `.pipeline/`; those stay with that run.
The destination run uses its own settings. When transferring acquisitions
between runs, refresh each affected run when its existing masters need updating.

## What should I not move separately?

- **One series folder such as `sample_s1/`:** its original image and saved state
  live outside it. Move the acquisition folder instead.
- **`.acquisition/` or its state/tuning files:** these belong with their
  original acquisition and series. Do not move or rename the internal folders
  independently.
- **The original acquisition alone:** separating it from the processed group
  breaks the project's ability to locate its source and rebuild results.
- **Individual active result files by cutting, renaming, or replacing them:**
  the processing state records their paths and relationships. A location update
  cannot reconstruct arbitrary renames or missing files. Use the supported
  processing and file-management actions; copy outputs when you only need an export.
- **The FIScH installation's `.venv`:** it is separate from the analyzed project
  and is not a portable installation. Install FIScH on each computer; rerun setup
  when relocating the application checkout itself.

Custom model weights stored elsewhere, machine-wide model caches, external log
folders, and unrelated files outside the project do not travel with it. Make
those resources available on the destination machine and reselect custom model
paths when necessary. An absolute custom-model path may need changing even if
you copied the weights inside the project.

## Move a whole project

1. Finish processing and save pending viewer edits. Close the project in FIScH
   before moving or copying it.
2. Move/copy the **entire project folder**, including `.pipeline/` and every
   acquisition's `.acquisition/`. Keep the internal filenames and layout.
3. Open FIScH on the destination computer and choose the project folder at its
   **new location**. The opened location takes precedence over an old saved
   `run_dir`.
4. Open **Manage files…** to read the summary, next steps and affected-file
   details. If location information is outdated, choose **Update paths and
   condition tags…**, review its changes, and
   apply them. The action checks the opened run, not only the selected series.
5. Inspect the refreshed master tables and confirm that the condition columns
   reflect your folder structure. Continue viewing or processing as required.

The update action is enabled only when there is something to refresh. If it is
disabled and FIScH reports no location issue, a move can already be fully resolved
through relative paths; you do not need to force an update.
A missing master table is not itself a location problem. New masters are
created by aggregation when the corresponding analysis workflow runs.

## What changes after a move?

**Moving/renaming only the outer project folder:** internal run-relative
experiment IDs and condition tags stay the same. Known saved run-owned paths,
such as the saved run directory, may need rebinding.

**Reorganizing acquisition/condition folders inside a run:** master-table
`experiment_id`, quantification `cell_id`, and `condition_level_N` tags are
refreshed for the new run layout. The acquisition and series folders themselves
are structural and are not condition tags.

Current per-experiment measurement tables use acquisition-local IDs and remain
unchanged during a location-only update. Their IDs need not equal the current
full run-relative IDs in the master. See [Output tables](output_tables.md#master-tables-and-condition-columns)
and [Analysis identifiers](analysis_identifiers.md) for the distinction.

**Image pixels, mask drawings, measurement values, and processing revisions are
preserved by a location-only update.** It does not run registration,
segmentation, tracking, quantification, or distance profiling. Rebuilding or
rerunning an analysis is a separate choice when numerical inputs have changed.

Path/tag refresh cannot recover a missing original, deleted scientific results,
or lost state. Keep those files together; use **Compact experiment…** for
supported space saving and the backup controls for retained versions.
