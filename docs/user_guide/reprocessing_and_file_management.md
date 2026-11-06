# Reprocessing and file management

[User guide](README.md) · [Previous: Analysis and results](analysis_and_results.md) ·
[Next: Troubleshooting](troubleshooting.md)

Use the saved run status to decide whether you need to resume processing, rerun a changed step, refresh locations, or free space. Open **Manage files…** and review its proposed changes before applying an action.

## Choose the right action

| What you want to do | Action | Effect |
| --- | --- | --- |
| Continue unfinished work | Run the enabled pipeline steps | Reuses completed outputs when their inputs/settings remain valid. |
| Apply changed processing settings or update outdated results | Rerun with overwrite, or use the applicable Rebuild action | Recomputes the reviewed results and any selected downstream work. |
| Open older results for editing | Migrate to FITS 4 | Adapts metadata/layout while retaining existing pixels and measurements; a full numerical rebuild is a separate optional choice. |
| Refresh a moved/reorganized run | Update paths and condition tags | Refreshes known location information and master identities/tags without numerical processing. |
| Remove unneeded intermediates/caches | Compact experiment | Keeps the retained scientific outputs and original acquisitions; creates no persistent backup. |
| Recover or remove a retained version | Manage backups | Restores a reviewed version or deletes selected backups. |

## Review overwrites and input conflicts

Execution runs channel registration before time registration; the GUI tab order
is unchanged. Disabled preprocessing steps are bypassed even if their old files
remain. Overwriting reads the preceding enabled stage and preserves its pixels.
Each artifact records its own UTC `created_at` revision and the paths/revisions
of its actual inputs in `derived_from`; existing step timestamps keep their
previous meaning. Analysis Parquets carry the same provenance.

Before a GUI or CLI run, FITS compares recorded input revisions with current
files and propagates conflicts downstream. The shared dialog lists affected
files and offers **selected step and downstream**, **selected step only**, or
**cancel** for an overwrite. Selecting only that step suppresses dependent work
for this launch. A later launch warns about remaining conflicts and offers
rebuilding, continuing with existing results, or cancelling. These checks use
embedded revisions, not filesystem modification times.

An overwrite alone needs no review when the experiment has no existing
downstream results. Quantification explicitly produces
`fits_quantification.parquet` and can be rerun directly; Distance Profile is an
independent analysis output. Likewise, overwriting background subtraction needs
no review if no dependent masks or measurements exist yet. Existing downstream
files require review when their steps are included. Bypassed downstream results
are preserved and receive a console warning if they are stale or affected by
the overwrite. FITS checks them again before reuse when their steps are included
later. Real upstream,
legacy-format and missing-input conflicts remain subject to review; changed
settings on a result explicitly selected for overwrite do not themselves
require a decision when its current inputs are available.

### Include, bypass, and reuse

Every step has an **Include in workflow** checkbox. Checked means the step's
output participates in the flow: FITS reuses valid existing results unless
**Overwrite** is selected. Unchecked means the step is bypassed and its saved
output is ignored when selecting downstream inputs. Existing files are kept.

Quantification selects its inputs from that included flow before checking which
files exist. It uses tracking when Tracking is included, otherwise segmentation
when Segmentation is included. Accepted tracking edits participate only when
Edit tracking is included. The intensity image similarly comes from the latest
included preprocessing stage, with converted raw images as the baseline.
Missing selected inputs are reported; FITS does not silently fall back to a
bypassed result. Measurements, provenance, compartment exports, and compartment
previews share this source selection. The numerical bioimagequant API is unchanged.

Include Segmentation or Tracking before including Quantification. The GUI warns
in orange when Quantification is selected without a mask producer, and blocks
launch with a red console message. The CLI raises the same configuration error
before processing. To reuse saved tracking for a Quantification rerun, leave
Tracking included and its Overwrite checkbox unchecked.

## Run status and read-only results

The browser status panel shows a coloured compatibility summary, followed by
image channels and the total run-directory size, including retained backups. **Details…**, beside **Manage files…**, opens a scrollable
explanation with read-only/upgrade guidance and retained-history size. Compatible
experiment folders appear green; outdated folders and their parents appear orange
with warning icons. If any active experiment has older metadata or layout, the run is marked
**Upgrade to FITS v4 required - read-only**. Viewers and settings remain available.
In read-only runs, **Back** and **Next** let you inspect both Convert and
processing settings; **Next** never starts conversion in this mode.

## Manage files controls

**Manage files…** groups current-file actions separately from **Manage backups**.
Current-file actions check the whole run and use three controls:

- **Rebuild** changes its name with the required work: **Rebuild all results…**
  for migrated or compacted experiments, **Rebuild outdated results…** for stale
  downstream outputs, or **Rebuild required results…** for a mixture. Current
  experiments remain untouched. Complete reconstruction reruns final outputs as
  well as intermediates; it can take a long time and may change results. A backup
  is retained first. The button is disabled when no rebuilding is needed.
  For pre-v4 runs this control initially reads **Migrate to FITS 4…**, with an
  optional full rebuild, unchecked by default. Migrated arrays receive their
  actual stage filename; canonical `fits_array.tif` is reserved for compaction.
- **Update paths and condition tags…** is enabled only when saved state/settings
  references or existing master-table identities/tags differ from the current
  run. Condition tags belong to the master tables. Portable per-experiment
  Parquets remain unchanged during a location-only update. Without a master and
  with coherent saved paths, there is nothing to update. Location differences
  appear as orange warnings in the main status, browser and Details.
- **Compact experiment…**, slightly separated, removes intermediate files and
  caches while keeping essential files. It creates no persistent backup.

In Manage files, run guidance appears on the left and file-action buttons on the
right. Actions that do not apply are greyed out; their tooltips explain why.

Current-file actions check the whole run, regardless of the selected series. The manager is also available with `uv run fits manage /path/to/run`.

### Reset to raw inputs (main GUI only)

The red **Reset to raw inputs** section resets the **whole run directory**, including
every experiment. It moves original acquisitions out of their portable folders and
permanently removes FITS results, REF/ROI drawings, measurements, settings, logs,
caches and FITS backup history. Unrelated files are preserved. Missing originals
or conflicting destination filenames block the reset before removal begins.

Reset cannot be undone and creates no backup. Make a manual backup first if you
want to keep any results. The confirmation requires typing **RESET**. After success,
FITS opens a fresh window on the same run directory with template settings, an
empty user name and a clear console. Cancelling confirmation or an unsaved-editor
close leaves the run intact.

## Read the review diagram

Conflict, migration, rebuild and compaction reviews share one schematic for the
whole run. Each icon represents a workflow stage and shows its file count and
actions. Originals have no filename in the diagram. Teal means all files are
kept, purple marks outputs to overwrite/rebuild, orange marks affected or changed
files, and blue dashed icons mark new files. Shared renames show the old name struck through, a downward arrow and the
new name, even when other files already have the target name.
Click a stage to list its actual files and individual actions, grouped by
acquisition and series. The list scrolls for larger runs; clicking the diagram
background clears it. Review windows open larger and retain readable icons.
Use scrolling, zoom or Fit to inspect the complete sequence. Arrows distinguish
workflow order from recorded provenance and REF/ROI geometry relationships.
Path/tag-only updates list the affected files and explain each change.
Migration summarizes those updates above its schematic, with the full plan under
collapsed **Details**. Its optional full numerical rebuild checkbox switches
between the move/rename overview and complete reconstruction. Switching the
preview does not change any files.

## Compact an experiment

Use **Manage files… → Compact experiment…**, or `uv run fits compact /path/to/run`, to
preview the exact retained and removed files. Compacting keeps the furthest
image as `fits_array.tif` and the active final object mask as `fits_masks.tif`,
including edited/filtered tracking when active. Original acquisitions, REF/ROI,
measurements, settings and reports remain. Superseded intermediates and viewer
caches are removed only after publishing and verifying the retained files and
state; publication failures roll back. If conflicts exist, choose rebuilding
first, deliberately retaining the existing downstream results, or cancelling.
Accepted conflicts remain recorded alongside the original provenance.

## Migrate older results or rebuild completely

Files from FITS versions before 4, or files lacking revision provenance, remain
viewable but read-only until explicitly migrated through **Manage files**.
Migration updates folder structure, metadata, paths, identifiers and condition
tags without rerunning processing or changing pixels/measurements. It retains
the original producer metadata and records that historical lineage is unavailable.
A saved final image becomes an accepted checkpoint: an experiment stopped after
background subtraction can proceed to segmentation without recreating earlier
intermediates. Migration itself remains metadata/layout-only by default. Its
optional **Rebuild all experiment results** choice reruns the complete workflow
from original acquisitions, including final images, masks and measurements.
**This can take a long time, and final results may change**, even with the same
settings. Existing experiment results and state are backed up before processing
starts; their original scientific files are retained in that backup. Compacted experiments require rebuilding missing inputs when needed
for an upstream processing change.

## Portable acquisitions and Manage files

Move complete projects or acquisition folders as described in [Moving a project: what is portable?](portable_projects.md). That guide explains which hidden metadata and originals must remain together, detached folders, and the steps for reopening a project at a new location.

For location-only updates, portable per-experiment Parquets remain unchanged; masters are refreshed for the current run layout. See [master IDs and condition tags](output_tables.md#master-tables-and-condition-columns).

## Backups and restoration

Retained backups are never deleted automatically by compaction. A storage hint
appears only when backups exist; delete reviewed snapshots through Manage
files to reclaim that space. Before migration or path/tag updates, FITS retains a complete original
run folder under `.fits/backup/<revision>/run/`, including original files,
metadata, settings and tables. This copy uses additional disk space; FITS checks
free space before migration and stops if the backup and working files will not fit. Restoring a
**Whole run** backup restores the original folder structure and file contents,
and retains the current run as another backup. Rebuilding existing results retains a per-experiment backup under
`.fits_experiment/backup/<series>/<revision>/`. A full rebuild replaces final
results as well as intermediates; it does not keep an old final image active
beside a new upstream chain. Per-experiment backups restore coherent outputs
and state. REF/ROI drawings are preserved;
if registration changes, inspect their alignment in the viewer before explicitly
accepting it through Manage files or recreating the drawings.

## Review REF/ROI alignment

REF/ROI drawings keep their pixels during metadata-only maintenance. Intensity-only updates do not invalidate their registration geometry. When registration changes, inspect the drawings over the current image before accepting their alignment through Manage files or correcting them. See [Reusing masks](reference_and_roi_masks.md#reuse-masks-after-processing-changes).
