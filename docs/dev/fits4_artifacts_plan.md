# FIScH 4: intermediate artifacts, provenance, and compacting

Status: all five implementation phases completed. No commits or publication.
Validation limits are recorded below.

Historical note: the original requirement to rebuild all pre-4 results has been
superseded by [file management actions](file_management_actions_plan.md). Migration
now preserves existing results; processing is a separate, explicitly chosen action.

## Agreed contract

- FIScH owns filenames, artifact roles, workflow order, dependency resolution,
  compatibility policy, user decisions, and compacting. Define names centrally in
  `fisch.environment.constant`; scope_io accepts supplied paths and remains unaware
  of FIScH filename conventions.
- Convert -> channel registration -> time registration -> background subtraction
  -> segmentation -> tracking -> optional edited tracking -> analysis. Keep the
  GUI registration-settings order unchanged.
- Independent image outputs: `proc_array_raw.tif`,
  `proc_array_reg_channel.tif`, `proc_array_reg.tif`, `proc_array_bgsub.tif`.
  Segmentation/tracking: `proc_masks_seg.tif`, `proc_masks_track.tif`.
- Each step reads its proper predecessor, skipping disabled optional stages.
  StepProfile declares inputs/outputs, including additional image/mask inputs.
  Execution, provenance, and the checker share input resolution.
- Generic scope_io provenance contains a UTC fractional-second `created_at`
  data-revision timestamp and `derived_from` input references with relative paths
  and their actual revision timestamps. Multiple inputs are supported. Processing
  or pixel edits create a revision; metadata-only rewrites, copies, renames and
  compacting preserve it. Existing run/step/channel timestamps retain their meaning
  and format. Analysis Parquets carry equivalent provenance.
- Use existing `pipeline_meta.version`, with FIScH 4.0.0 as the boundary. No
  separate schema-version field. Newly generated outputs record their producing
  FIScH version. Pre-4 results are read-only; missing/unverifiable provenance is
  not silently invented. Original acquisition files are valid external inputs.
- A temporary ordered inventory checks actual recorded inputs and propagates
  conflicts downstream. Reference/ROI and analysis branches have explicit input
  checks. No persistent stale-file list or automatic legacy migration.
- GUI and CLI share explicit preflight decisions and list affected experiments,
  steps and outputs. Overwrite choices: selected step + downstream, selected
  step only, cancel. Existing conflicts: rebuild affected, continue unchanged,
  cancel. Selected-only suppresses dependent work in that launch.
- Legacy warning: rebuild results or cancel. Explain required original inputs,
  potentially substantial runtime, possible changed results from new dependency
  versions, and any manually generated inputs needing intervention. Preserve
  earlier results while producing new intermediate outputs.
- Compact previews the identical keep/rename/delete set that will be applied.
  Conflicts: rebuild downstream then compact, retain existing downstream results
  and compact, cancel. The latter deliberately selects the furthest existing
  image/mask, including active edited tracking, even when outdated. Preserve
  original provenance and record acceptance of conflicts.
- Canonical compacted outputs: `proc_array.tif`, `proc_masks.tif`. Record compacted
  state/authoritative paths without rewriting historical input references.
  Preserve acquisitions, reference/ROI files unchanged, measurements, settings,
  and processing history. Delete superseded intermediates/caches only after
  verifying retained outputs. Reprocessing rebuilds missing prerequisites from
  original inputs.
- Existing tools resolve intermediate/compacted files and supported legacy files.
  Legacy data remain read-only. Appropriate controls follow artifact type;
  tracking-only tools are not meaningful for segmentation/reference/ROI layers.
  A broader multilayer general-viewer redesign is separate.

## Phase 1 — metadata and artifact definitions

Status: completed.

- Add generic revision/input metadata in scope_io, including preservation rules.
- Centralize FIScH 4 names/roles and compatibility utilities.
- Validate metadata round trips, distinct revisions and metadata-only preservation.
- Do not label partially implemented pipeline outputs as FIScH 4 prematurely.

Validation: 163 tests passed (`tests/test_artifact_provenance.py` and
`scope_io/tests`). Generic references preserve metadata-only revisions; FIScH owns
all new names. Existing run/step timestamp format is unchanged.

## Phase 2 — StepProfile and execution

Status: completed.

- Introduce shared input resolution and independent intermediate outputs.
- Apply channel-before-time execution across batch/conveyor/interactive modes.
- Record actual input provenance in images, masks, and analysis tables.
- Adapt state/discovery and existing tool paths sufficiently to keep workflows usable.
- Validate optional stages, overwrite inputs, and pipeline resumes.

Validation: a real TIFF pipeline test verifies separate raw/channel/time/bg
outputs, unchanged upstream pixels and correct recorded parent revisions. A
second run bypasses the disabled time stage despite its old file remaining.
Batch now uses the same StepProfile resolver as conveyor/interactive execution.
State/analysis tests and GUI result-name fixtures were updated during final
integration. Tuners and manual drawing resolve the configured image chain too.

## Phase 3 — checker and interactive decisions

Status: completed.

- Implement ordered inventories, direct/transitive conflicts and legacy checks.
- Present one shared decision interface from GUI and CLI, with explicit plans.
- Apply rebuild/selected-only/continue/cancel without persistent stale lists.
- Validate scope, cancellation, missing inputs, and read-only enforcement.

Implemented shared metadata-only inventories, actual/configured input checks,
transitive propagation, explicit decisions and queued main-thread dialogs in
GUI/CLI. Plain Python callers must supply a decision callback when conflicts
exist. Final GUI tests exercise all overwrite/legacy decisions. REF/ROI branches
compare inherited registration revisions (falling back to retained registration
step metadata for older drawings), independently of intensity revisions. Older
compatible branch metadata is refreshed without decoding or changing pixels.
Missing raw prerequisites can be restored from acquisition before downstream
rebuilding; the preview lists those required outputs as well.

## Phase 4 — compacting

Status: completed.

- Build reviewable compact plans and safe canonicalization/state updates.
- Support explicit acceptance of stale downstream results.
- Preserve reference/ROI and earlier provenance; remove only planned intermediates.
- Validate cancel/failure behavior, conflicts, legacy blocks and compacted resumes.

Validation: compact tests cover pixel/revision retention, unchanged REF/source
bytes, cancellation, changed-preview rejection, publication/state-save rollback,
compacted-run rebuilds, preserved legacy results and missing-raw reconstruction.
The real segmentation/tracking/analysis test deliberately retains stale tracking
when compacting and verifies its original revision and acceptance marker. A Qt
test publishes through the shared background compact writer.

## Phase 5 — viewer coverage and final integration

Status: completed.

- Finish intermediate/compacted/legacy loading and artifact-appropriate controls.
- Enforce read-only legacy operation in editing and channel-label tools.
- Complete FIScH 4 version activation, documentation and end-to-end validation.
- Record focused success separately from unavailable native Windows/hardware checks.

Validation:

- Main/core and scope_io combined suite: 548 tests passed, including the final
  missing-raw regression; final focused integration: 11 tests passed.
- Artifact-specific file/session/GUI coverage: 21 tests passed, including every
  supported filename, legacy read-only saves, and registration-vs-intensity
  branch dependencies.
- Shared decision dialogs and real Qt compact publication: 5 tests passed.
- Registration tuner and main-window GUI group: 93 tests passed. Conversion
  navigation: 8 passed; CLI interaction: 3 passed; pipeline mask/editor join: 3
  passed. Other isolated GUI groups passed as recorded in the execution run.
- The propagation-preview group passes all 24 tests after keeping the worker
  alive until its thread is joined during cleanup.
- Compilation, parent/submodule whitespace checks and `fits compact --help`
  pass. FIScH 4.0.0 was installed into the existing editable environment offline,
  without changing dependency versions.
- Broader offscreen GUI checks encounter native Qt/pyqtgraph cleanup crashes in
  `tests/gui/test_viewer.py` and `tests/gui/test_brush_performance.py`; those
  entire groups are not counted as passing. This does not constitute validation
  on native Windows, a real GPU backend or representative large acquisitions.
  Those checks remain outstanding.

## Execution log

- Plan created before implementation. Existing working tree inspected.
- User clarified: disabled optional preprocessing stages must be bypassed.
- User clarified: REF/ROI pixels survive intensity-only changes; only changed
  registration invalidates their geometry. Update compatible branch metadata
  without redrawing pixels; report geometry changes for review.

- Final integration preserves metadata revisions through channel-label changes,
  including Parquet metadata, and keeps backup history out of active discovery.
- Pyqtgraph is pinned to FIScH's PySide6 binding so dependencies importing another
  Qt binding cannot select incompatible widget/enum types.
- README and the implemented TODO section now describe FIScH 4 behavior.
- Removed unnecessary version-prefixed mask constant aliases: the established
  constant names directly define current filenames; legacy names stay in the
  compatibility lists.
- Follow-up: exclude `.pipeline` snapshots/caches from saved-experiment and raw-input
  discovery. Retained backups state snapshots previously caused repeated rebuild
  prompts after a successful rebuild. A real rebuild-then-compact regression now
  verifies compacting completes in the same flow and a second compact does not
  inspect the backups as active experiments.
- Follow-up: report/error windows have a screen-bounded initial size, resize grip,
  maximize control and scrollable overview/original text. Long compact and pipeline
  errors use this window instead of an expanding fixed-size message box. Compact
  cancellation logs now distinguish conflict review from closing the file preview.
