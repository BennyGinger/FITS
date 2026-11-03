# Portable acquisitions, file management and run status

Status: all six phases implemented and verified locally. Existing FITS 4 work preserved; no commits or publication.

The migration/rebuild boundary and Manage files presentation were revised in
[file management actions](file_management_actions_plan.md): migration preserves
results; missing-intermediate reconstruction is optional; downstream updates
rerun only explicitly reviewed affected work.

## Agreed behavior

- A run root contains `.fits/fits_settings.toml` or `.fits/logs/`. The opened root overrides saved run_dir values. Selecting a processed acquisition/series automatically opens its nearest containing run and preserves the browser selection. Processed orphan folders are reported; fresh raw-only folders remain valid inputs.
- Convert groups each original acquisition and all series under `<stem>/`: `<stem>/<original filename>` and `<stem>/<stem>_sN/`. Recognize existing groups; reject ambiguous/colliding destinations. FITS owns these paths, not fits_io.
- Acquisition-local `.fits_experiment/` contains `experiment_state/<series>/experiment_state.json`, `tuning/<series>/`, `cache/<series>/`, and `legacy/<series>/<revision>/`. A legacy revision keeps its state directly beside its retained outputs. Hide this metadata directory on Windows; do not rename or individually hide state JSON files. Run `.fits` keeps run settings/logs/reports.
- Stored paths resolve relative to acquisition/series anchors, independently of state JSON location. Moving a complete acquisition carries original data, series, settings, cache and history. Moving a whole run preserves run-relative identity.
- Quantification experiment_id/cell_id use the full series path relative to the run root, excluding the run folder name. Condition tags exclude the structural acquisition wrapper. Refresh paths/tags using existing tables; preserve measurements and data revision timestamps. Regenerate destination master tables without rerunning measurements. Actual image/mask rebuilds rerun affected quantification.
- Detect old layout or incompatible metadata before execution. If any active experiment is outdated, mark the entire run outdated/read-only; viewers/settings remain available, processing and compact are blocked until explicit upgrade. Preserved history never makes an active run outdated. Dedicated inventory/updater code handles old structures; normal execution uses the new layout.
- Manage files previews actions and exact scope. Migrate, Update paths/tags and Update downstream always check the whole run, regardless of browser selection. Migration preserves existing results and records unavailable historical lineage. Missing-intermediate reconstruction is optional; downstream processing is separate. History actions follow the selected series/acquisition, or whole run. Restore uses a coherent output/state snapshot; restoring incompatible results restores read-only status until migration. Delete legacy previews files and recoverable bytes, preserving active data. Cancel/failure preserves data with rollback. Do not guess unknown associations or rewrite arbitrary strings.
- Two stacked browser panels: top summary follows selection (run aggregate otherwise), showing file inventory/status, converted raw channels, retained backups size, and Manage files. Bottom retains current browser. Whole-run outdated status is explicit.
- Compact handles active intermediates only. When history exists, show its disk usage and a Manage files cleanup hint; omit the hint when no history exists.
- Restore reserved Advanced space only for Runtime settings so the run directory/browser area stays useful. Step tabs/subtabs retain their current expandable layout.
- Protocol loading is outside this work.

## Phases

1. **Paths, grouping and state persistence** — completed
   Centralize acquisition metadata paths; group conversion inputs safely; relocate new states; exclude internal directories; verify portable state/input resolution.
2. **Read-only inventory and run-root navigation** — completed
   Recognize roots/legacy/orphans, rebind current run root, gate mixed runs in GUI/CLI, preserve viewer access.
3. **Structure upgrades and table refresh** — completed
   Reviewable rollback-protected relocation and provenance audit; update IDs/conditions and masters; integrate necessary processing rebuilds.
4. **History management and compact integration** — completed
   Preview restore/delete, preserve coherent snapshots, adapt compact to relocated metadata, conditional space hint.
5. **GUI summary, Manage files and Runtime layout** — completed
   Add contextual summary/actions and runtime-only reserved expansion; keep normal tab/subtab layout.
6. **Integration, documentation and verification** — completed
   Exercise multi-series conversion, moves, mixed legacy runs, upgrades/cancellation/rollback, table values, history and GUI. Update README/TODO and record actual validation limits.

## Progress

- Plan recorded before implementation. Existing uncommitted FITS 4 changes inspected and retained.

- Phase 1: real TIFF conversion/grouping and moved-run state/input resolution pass (2 focused tests). Source collision/idempotency tests preserve both originals.

- Phase 2: root promotion, fresh/orphan handling and mixed-run read-only inventory pass (4 focused tests total). Internal history stays out of active compatibility checks.

- Phase 3: real-file relocation, condition/ID refresh after a second move, measurement preservation and injected-failure rollback pass (6 focused tests total). Rebuild-required upgrades retain a pending marker until completed; ordinary execution remains gated.

- Phase 4: real snapshot exchange, active-revision restoration, history deletion without touching active images, and conditional compact space hints pass (7 focused tests total).

- Phase 5: offscreen GUI checks pass for contextual channels/status, mixed-run blocking with viewer access retained, root promotion preserving selection, and unchanged Runtime height on expansion while step Advanced remains collapsible (2 GUI tests).

- Phase 6: core, workflow and fits_io suites pass: **562 tests**. Focused offscreen GUI suites pass: **85 tests**, including portable file management, Runtime/step Advanced behavior, navigation, CLI interaction, resizable reports and artifact decisions. Python compilation and both repository/submodule diff whitespace checks pass.

- Integration covers actual TIFF conversion, multiple series sharing one original, moved run/acquisition paths, condition/identifier refresh preserving measurements, mixed-run gating, numerical upgrade cancellation/resumption, rollback, snapshot exchange/deletion and compact history hints. An upgrade rebuilds only incompatible acquisitions, preserving healthy FITS 4 output bytes/revisions. Affected series retain a coherent snapshot of outputs/state and copies of manual REF/ROI drawings; compatible retained tables can be refreshed without measurements being rerun.

- Registration changes require explicit REF/ROI review. Manage files offers acceptance only for a pending upgrade after the user has inspected alignment; it validates axes/shape/channels, preserves drawing pixels and records the reviewed geometry. It does not silently adopt new registration dependencies.

- Validation limits: GUI checks used Linux/offscreen Qt and small synthetic TIFFs. Native Windows hidden attributes/rendering, large acquisitions, GPU backends and real ND2 reader integration were not exercised in this pass. No user experiment data was moved or rebuilt during verification.
