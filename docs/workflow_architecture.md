# Workflow responsibilities

| Package | Responsibility |
| --- | --- |
| `definitions/` | Step profiles/specifications, registry and configured input selection. |
| `experiments/` | Acquisition grouping, run-root recognition, source discovery and state assembly/persistence. |
| `metadata/` | Run/step metadata models and serialization values. |
| `artifacts/` | Artifact paths/provenance and REF/ROI geometry dependencies. |
| `checks/` | Run compatibility, saved-input revision checks, downstream conflict propagation and preflight decisions. |
| `file_management/` | Explicit migration, relocation/path/tag updates, numerical reconstruction plans, compaction publication and retained history. |
| `runtime/` | Batch, conveyor and interactive execution; run decisions, progress and errors. |

`fits.pipeline` coordinates these responsibilities. Numerical implementations
remain in `fits.tasks` and their submodules; GUI dialogs remain in `fits.gui`.
The top-level `fits` package contains the pipeline entry point and package files;
supporting implementations live in the responsibility packages below it.

## Experiment and artifact inspection

- `experiments/acquisitions.py`: group an original acquisition and its series.
- `experiments/roots.py`: recognize run roots and resolve selections inside
  processed experiments.
- `checks/compatibility.py`: `inspect_run_compatibility()` inventories format/layout
  problems; `require_current_run()` enforces the read-only boundary before migration.
- `checks/artifacts.py`: `inspect_run()` compares recorded input revisions with
  current files, propagates conflicts and builds the preflight report.
- `checks/locations.py`: `inspect_locations()` checks portable state/settings
  references and streams identity/tag columns from existing masters. It does not
  classify location differences as scientific provenance conflicts. Missing
  masters do not imply an update is needed.
- `checks/decisions.py`: `apply_decision()` resolves explicit pre-run choices into
  a settings copy without modifying artifacts.
- `checks/planning.py`: shared workflow ordering and rebuild-source selection.
- `checks/models.py`: compatibility reports, artifact records and preflight reports.
- `checks/space.py`: shared free-space guard and raw/final-array output estimates.
- `checks/pipeline.py`: count pending enabled outputs before pipeline execution.
- `artifacts/provenance.py`: metadata reading, compatibility, input references and
  creation of output revision metadata. FITS-specific logic stays out of fits_io.
- `artifacts/paths.py`: locate current/compacted images and resolve viewer/tuner
  inputs through the same step contracts used by execution.
- `artifacts/branch_masks.py`: validate REF/ROI registration dependencies and
  refresh accepted metadata without changing drawing pixels.

Format/layout status is separate from stale-result checks: a run can use the
current format while some downstream results need attention.
Execution completion is separate from both: `runtime/run_decision.py` uses
`decide_run()` to identify completed and pending work, while
`runtime/scheduler/planning.py` selects enabled steps.

Pipeline space is checked before logging/settings publication or numerical work,
then pending steps check again through task preparation (conversion checks before
acquisition grouping). File-management planners and executors use the same
space guard. Deleting retained history requires no extra data-copy budget.

## File management

Start with `file_management/api.py` for the run-wide actions. Its implementation
is divided by responsibility:

- `migration.py`: adopt existing results as compatible checkpoints while
  preserving original metadata and recording unavailable historical lineage.
- `relocation.py`: shared folder moves, known-path rebinding, table identifiers,
  master-table condition tags and refresh. Location-only updates preserve portable
  per-experiment Parquet bytes. It does not launch processing.
- `transactions.py`: reversible file moves/replacements and failure rollback.
- `rebuild.py`: reviewed numerical processing plans, series/step scope and
  execution verification, including optional complete rebuilding after migration.
  Full rebuilding retains backups, replaces final results, validates ordinary
  provenance and removes superseded active filenames. `plan_required_rebuild()`
  combines full reconstruction for migrated/compacted series with downstream-only
  scopes for other stale series, leaving current experiments untouched.
- `snapshots.py`: preserve a coherent result/state set before an explicit rebuild.
- `run_history.py`: retain a complete original run folder before migration or path/tag updates;
  restore its exact files, metadata and layout while retaining the displaced run.
- `history.py`: inventory, restore and delete reviewed retained snapshots.
- `compaction.py`: preview retained/removed artifacts, publish canonical outputs,
  verify them and roll back failed publication. Its entry points are also exposed
  through `file_management/api.py` for GUI/CLI callers.

Package initializers avoid eager imports of inspection/execution modules. Import
the specific module or the file-management API instead of introducing a second
set of module aliases at the workflow root.

## Shared user interfaces

- `fits.gui.file_management.manager`: the GUI/CLI Manage files entry point, with
  Experiment files and Manage backups sections.
- `fits.gui.file_management.compaction`: conflict review and exact compaction preview.
- `fits.gui.file_management.tasks`: shared responsive execution of reviewed file writes.
- `fits.gui.file_preview`: reusable document-icon rendering, per-file change lists
  and adapters for reviewed migration, processing, compaction and restore plans.
  `overview.py` aggregates stages across the run, deduplicating shared originals;
  `stage_files.py` lists exact per-file actions grouped by acquisition and series.
  These are temporary presentation models, not another persisted artifact registry.
- `fits.gui.artifact_lineage`: recorded conflict dependencies and geometry-only
  REF/ROI relationships, adapted into the same file-preview renderer.
- `fits.gui.run_result.dialog`: shared completion summary, full-report access and
  successful-run management navigation.
- `fits.gui.run_result.report`: resizable, scrollable presentation of the full report.
- `runtime/progress/outcome.py`: Qt-independent success/failure/cancellation
  classification; intentional drawing skips are not failures.

Main-window completion waits for worker shutdown before opening management. The
interactive CLI uses a local Qt event loop, allowing nested maintenance without
quitting the main application or showing duplicate completion dialogs.
