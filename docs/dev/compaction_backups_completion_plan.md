# Compaction, backups and shared run completion

1. **Artifact and storage names — completed.** Rename migrated un-compacted final arrays to their actual stage filename without recomputing pixels. Reserve canonical names for compacted outputs. Use compaction APIs and UI wording and retained storage to backup, keeping old persisted state/history readable at the storage boundary.
2. **File management — completed.** Group current-file actions separately from backup management, place Compact experiment apart from migration/update/rebuild, retain concise backup availability/size, and explain all actions in tooltips. Retain restorable versions before replacement operations; compaction does not create a persistent backup.
3. **Main status panel — completed.** Access compaction through Manage files instead of a standalone main-window button. Present a distinct coloured status summary, then channels and total run-directory size.
4. **Shared completion — completed.** Classify progress without Qt, and share one completion/report dialog between GUI and interactive CLI. Successful intentional drawing skips remain successful. Offer file management only for successful compactable runs; preserve GUI navigation and suppress full-run completion during Convert → Next and nested maintenance work.
5. **Validation and documentation — completed.** Test artifact renaming/provenance, backup retention/restoration, compaction, outcome classification, GUI/CLI routing and navigation. Run Pyright and whitespace checks; update current documentation with verified results.

## Verification

- 684 core, workflow, FIScH I/O and progress tests passed.
- 99 focused GUI/CLI tests passed, including success/failure/cancellation, intentional drawing skips, nested CLI maintenance, full-report access and navigation preservation.
- Pyright standard-mode checks report zero errors and warnings for the reviewed production modules and new focused tests.
- Shared GUI functions have parameter/return annotations and docstrings; whitespace checks pass.
- Migration/final-stage naming, unchanged optional-build finals, backup restore/rollback, exclusion of backup states from active discovery, compaction without a retained backup, and earlier persisted state/history compatibility are covered.
- Visual inspection used Linux/offscreen Qt. Native Windows, real ND2/GPU processing and large-dataset copying were not exercised.

The technical package guide moved from the workflow package into
[workflow_architecture.md](workflow_architecture.md). The root README is the
user-facing entry point and uses backups/compaction terminology throughout.

## Rebuild policy follow-up

The earlier missing-intermediate-only option and final-image preservation
exception have been superseded by [full rebuilding](full_rebuild_plan.md).
Migration remains numerical-processing-free unless its optional rebuild is chosen.
