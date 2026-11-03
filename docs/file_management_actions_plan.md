# File management: migration, updates and downstream processing

Status: implemented and verified locally. This supersedes the earlier requirement to
rebuild every pre-4 artifact during an upgrade.

1. **Migration and shared path executor** — completed. Preserve existing image
   pixels and measurements; adopt legacy final outputs as explicit checkpoints,
   retain original producer metadata, and record unavailable historical lineage.
   Keep folder/table relocation shared with ordinary path/tag updates.
2. **Processing API and checks** — completed. Separate optional reconstruction of
   complete optional rebuilding from rerunning selected stale downstream results. Scope processing
   to affected series/steps, preserve unrelated work, and expose the shared checker
   on GUI load and immediately before GUI/CLI execution.
3. **Manage files presentation** — completed. Two sections with always-clickable actions:
   Migrate to FITS 4 / Rebuild all experiment results, Update paths/tags,
   Rebuild outdated results, and a separated Compact experiment action. Explain
   no-op actions in the window. Manage backups shows availability/size, reasons,
   restore and delete controls; do not duplicate the directory browser.
4. **Verification and documentation** — completed. Exercise real legacy arrays/masks/
   tables, resume from checkpoints, rollback, rebuild scope, warning presentation,
   GUI/CLI integration and history. Update current user documentation.

Migration never reconstructs historical provenance. A new migration revision is
an adoption event, not an original processing timestamp. A migrated checkpoint
can feed new downstream steps without requiring absent earlier intermediates.
Migration alone leaves scientific values unchanged. An optional full rebuild
reruns final images, masks and measurements as well as intermediates. It can take
a long time and may change final results. Existing results are backed up first.

Migration and path/tag updates retain a complete pre-change run copy under
`.fits/backup/<revision>/run/`. This preserves original folder structure, files,
metadata, settings and tables without reverse-converting metadata. Manage files
shows these as **Whole run** backups, including when a series is selected.
Restoration exchanges the run folders transactionally and retains the displaced
run as another backup. Existing root history and the active write lock stay in
place. Migration or restore failures roll back without publishing an incomplete
backup. This includes copying original acquisition files and uses corresponding
additional disk space. Earlier migrations that retained no copy cannot be
promoted retrospectively into exact original backups.
Available disk space is checked before all reviewed file-management actions and
again at execution. The shared guard lives in `workflows/checks/space.py`.
Migration budgets the retained folder and rewrite workspace; path/tag updates,
compacting and metadata edits budget their outputs and temporary copies. Rebuilds
use the raw FITS array size (or preserved final array, falling back to the
original acquisition) multiplied by the number of scheduled outputs, plus
headroom. Restoration budgets metadata writes; deleting history remains possible
without a data-copy budget. The whole GUI/CLI pipeline uses the same estimates
before processing, with additional checks before pending individual steps.
Insufficient space stops the action with the estimated requirement and available
bytes and asks the user to free space. Later copy/write failures during file
transactions still roll back; completed processing remains preserved.

## API boundaries

- `workflows/file_management/api.py`: run-wide `plan_migration`/`migrate`,
  `plan_update`/`update`, `plan_downstream_update`/`update_downstream`, and optional
  `plan_full_rebuild`. A no-op plan returns `None` for the UI to explain.
- `workflows/file_management/migration.py`: adopt compatible checkpoints,
  preserve original producer/step metadata, establish explicitly accepted baseline
  references only to files that exist, and identify completed imported stages.
- `workflows/file_management/rebuild.py`: reviewable numerical plans and execution
  scope. Calls the normal pipeline through the GUI/CLI callback. Includes the older
  explicit full-rebuild/pending-run helpers, now isolated from relocation.
- `workflows/file_management/compaction.py`: compact preview, verified publication
  and rollback, exposed through the file-management API.
- `workflows/file_management/run_history.py`: complete pre-migration folder copies
  and transactional whole-run restoration with displaced-run retention.
- `workflows/file_management/relocation.py`: shared relocation, known-path rebinding, table ID/tag
  updates and rollback. Migration adds metadata adoption through this executor;
  ordinary Update uses the same executor without changing historical provenance.
- `workflows/checks/artifacts.py`: shared load-time/pre-run checks. Missing outputs
  for new steps are ordinary work; missing required inputs and changed recorded
  revisions are warnings. Imported checkpoints do not pretend to have absent
  earlier inputs. New/replaced upstream files remain detectable afterward.

The full package organization is documented in the
[workflow responsibility map](workflow_architecture.md). Run compatibility
lives in `workflows/checks/compatibility.py`; history, snapshots and transactions
live alongside the file-management actions. Artifact provenance and viewer paths
remain in `workflows/artifacts/`, separate from the shared checking workflow.

The GUI/CLI manager never launches processing for plain migration. A separate
accepted `ProcessingPlan` enters `start_pipeline(..., maintenance=plan)`; its
series/step scope is temporary runtime context and is not saved as a validity list.

## Validation

- **572 core/workflow/fits_io tests passed**, plus **98 focused offscreen GUI
  tests**. After the final conversion-metadata refinement, **20 focused migration,
  conversion and FITS 4 execution tests passed**.
- Real-file cases cover legacy TIFF/mask/Parquet migration preserving pixels and
  measurements; original producer metadata; segmentation directly from an adopted
  preprocessing checkpoint; tracked masks whose earlier segmentation is absent;
  optional image/mask reconstruction (superseded by full rebuilding below);
  healthy sibling-series preservation; scoped stale-result updates; moved run
  settings and paths; rollback after an injected metadata/table failure; and
  compacting accepted migrated finals without rerunning processing.
- GUI cases cover load-time revision warnings without automatic dialogs or a
  whole-run format lock, folder icons/colors, migration-only versus optional
  reconstruction choices, actual migration without a processing callback, and
  always-clickable no-op actions with an explanation inside Manage files.
- Python compilation, repository/submodule whitespace checks and CLI manager help
  pass. Native Windows rendering/hidden attributes, real ND2 multiseries decoding,
  GPU backends and large datasets were not exercised. Multi-series control flow
  used TIFF-backed readers. No user experiment data was modified during validation.

## Compaction and completion follow-up

The implementation and validation of stage-specific migration filenames,
`backup/` storage, automatic replacement backups, shared completion dialogs and
GUI navigation are recorded in [the follow-up plan](compaction_backups_completion_plan.md).
The technical package map is [workflow architecture](workflow_architecture.md).

The optional partial-intermediate mode has been replaced by
[full rebuilding](full_rebuild_plan.md). Migration still defaults to no numerical
processing. Its optional rebuild now includes final arrays, masks and measurements.
