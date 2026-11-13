# Manage files

[Guide home](../README.md)

Related: [File-management overview](../reprocessing_and_file_management.md) · [Channel labels](channel_labels.md) · [Backups](backups.md) · [Portable projects](../portable_projects.md)

## Manage files controls

**Manage files…** groups current-file actions separately from **Manage backups**.
Current-file actions check the whole run and use three controls:

- **Rebuild** changes its name with the required work: **Rebuild all results…**
  for migrated or compacted experiments, **Rebuild outdated results…** for stale
  downstream outputs, or **Rebuild required results…** for a mixture. Current
  experiments remain untouched. Complete reconstruction reruns final outputs as
  well as intermediates; it can take a long time and may change results. A backup
  is retained first. The button is disabled when no rebuilding is needed.
  For older read-only runs this control initially reads **Migrate to FIScH 5…**, with an
  optional full rebuild, unchecked by default. Migrated arrays receive their
  actual stage filename; canonical `proc_array.tif` is reserved for compaction.
- **Update paths and condition tags…** is enabled only when saved state/settings
  references or existing master-table identities/tags differ from the current
  run. Condition tags belong to the master tables. Portable per-experiment
  Parquets remain unchanged during a location-only update. Without a master and
  with coherent saved paths, there is nothing to update. Location differences
  appear as orange warnings in the main status, browser and Details.
- **Compact experiment…**, slightly separated, removes intermediate files and
  caches while keeping essential files. It creates no persistent backup.

In Manage files, the left panel has three sections: **Summary** explains what
needs attention, **What to do next** describes what the relevant action would do,
and expandable **Details** lists affected files and checker reasons in a
scrollable report. The file-action buttons sit on the right; actions that do not
apply are greyed out. Backups remain in their own section below.

If included experiments or their measurements change, the summary explains that
the master tables are out of date. **Rebuild analysis…** combines the currently
included experiments using valid individual measurements; it does not rerun
image processing when those measurements are current.

Current-file actions check the whole run, regardless of the selected series. The manager is also available with `uv run fisch manage /path/to/run`.

### Channel labels

The **Channel labels** subsection starts with a full-width explanation. Below
it, a compact editable table on the left shows expected colours where available,
and the affected-file preview is on the right. The bottom row shows status on
the left and **Rescan** / **Save new labels** together on the right.
**Rescan** refreshes the inspection; **Save new labels** reviews
and confirms a run-wide rename. It is disabled until valid changes are entered.
Renaming preserves image pixels and channel order. Conflicting file actions are disabled while labels are being saved. Closing
waits for any background inspection to finish.
Read-only runs must be migrated before renaming.

See [Renaming channels](../channels_and_labels.md#rename-channels-in-an-existing-run)
for the affected artifacts and naming rules. The **ⓘ** button beside
**Experiment files** opens this chapter in the shared help window.

### Reset to raw inputs (main GUI only)

The red **Reset to raw inputs** section resets the **whole run directory**, including
every experiment. It moves original acquisitions out of their portable folders and
permanently removes FIScH results, REF/ROI drawings, measurements, settings, logs,
caches and FIScH backup history. Unrelated files are preserved. Missing originals
or conflicting destination filenames block the reset before removal begins.

Reset cannot be undone and creates no backup. Make a manual backup first if you
want to keep any results. The confirmation requires typing **RESET**. After success,
FIScH opens a fresh window on the same run directory with template settings, an
empty user name and a clear console. Cancelling confirmation or an unsaved-editor
close leaves the run intact.
