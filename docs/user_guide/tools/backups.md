# Backups and restoration

[Guide home](../README.md)

Related: [Manage files](manage_files.md) · [File-management overview](../reprocessing_and_file_management.md) · [Portable projects](../portable_projects.md)

## Backups and restoration

Each backup row has a **restore** icon (a clock with a backward arrow) and a
**bin** matching SegTune. These act on the backup beside the clicked icon,
regardless of previous selection. Both open a review before changing files.
The bottom row shows selection/status text on the left and **🗑 Delete all
backups…** on the right. Delete all reviews every backup currently shown in
the list, including unselected rows; backups outside the list and current
results are preserved. The list follows the selected experiment and also
includes applicable whole-run backups.

Retained backups are never deleted automatically by compaction. A storage hint
appears only when backups exist; delete reviewed snapshots through Manage
files to reclaim that space. Before migration or path/tag updates, FIScH retains a complete original
run folder under `.pipeline/backup/<revision>/run/`, including original files,
metadata, settings and tables. This copy uses additional disk space; FIScH checks
free space before migration and stops if the backup and working files will not fit. Restoring a
**Whole run** backup restores the original folder structure and file contents,
and retains the current run as another backup. Rebuilding existing results retains a per-experiment backup under
`.acquisition/backup/<series>/<revision>/`. A full rebuild replaces final
results as well as intermediates; it does not keep an old final image active
beside a new upstream chain. Per-experiment backups restore coherent outputs
and state. REF/ROI drawings are preserved;
if registration changes, inspect their alignment in the viewer before explicitly
accepting it through Manage files or recreating the drawings.
