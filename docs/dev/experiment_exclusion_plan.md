# Experiment exclusion

## Agreed behavior

- Exclusion is available after conversion, per series, and applies to all processing and analysis.
- Persist `excluded: bool = False`; only explicit JSON `true` excludes. Missing flags remain active.
- Preserve exclusion through rebuilds and retain individual scientific outputs.
- Discovery remains complete for browsers and inspection. Share active-state filtering across execution, checks and aggregation.
- Legacy migration without full rebuilding keeps all experiments active. Full rebuilding permits selection after conversion.
- A change in active membership makes combined analysis outdated. Rebuild masters from valid active-series results; rebuild missing/outdated analysis first where required. Remove stale masters when no active results remain.
- Browser multi-selection covers descendant experiments once. No selection or a running pipeline disables the action. All excluded means Re-include; otherwise Exclude, including mixed selections.
- Place the exclusion button on the right of the Selected path display, without a separate counts label. Keep the viewer, tracking editor, channel-label and report buttons on a separate row below (updated by follow-up UI request). Folder badges propagate to portable acquisition and ancestor folders: none for active, amber half-circle for mixed, gray circle-minus and muted text for excluded. Keep inspection available.

## Implementation progress

### Selected-only processing follow-up

- [x] Follow-up: toggle **Exclude others** / **Re-include others** from the outsiders' saved state, disable an empty complement, and use smaller fonts for both action buttons. Re-including others preserves the selected experiments' inclusion. Persistence, mixed selection and layout checks pass: **53 focused tests**, **Pyright 0 errors and 0 warnings**, and clean `git diff --check`.

- [x] Add **Exclude others** beside **Exclude exps.** / **Re-include exps.** in the selection row.
- [x] Reuse saved exclusion and the writer lock to activate the selected converted experiments and exclude the others; preserve existing migration restrictions.
- [x] Summarize multiple selected folders and covered experiments in the Selected display. Preserve wrapping and let the display take height from the tree, with tool buttons on their own row below.
- [x] Validate selected-only overwrite, migration restrictions, browser actions and wrapping; run Pyright.

Validation: **122 tests passed** across exclusion persistence, browser/exclusion GUI,
conversion, conversion navigation and the main window. The overwrite check verifies
that only the selected series is regenerated and excluded sibling outputs are
preserved. The layout check verifies that long selection text wraps by reducing
the tree height while the browser size stays fixed. Pyright on changed Python
modules and tests reports **0 errors, 0 warnings**, using an explicit temporary
configuration for the current environment and workspace package sources.
`git diff --check` passed.

- [x] Read global AGENTS.md and inspect existing state, execution, checks, aggregation and browser utilities.
- [x] Add durable state field and centralized active-state/selection helpers.
- [x] Filter batch, conveyor, interactive execution and processing checks; preserve exclusion through conversion/rebuilds.
- [x] Track master membership and expose analysis rebuild without surgical row deletion.
- [x] Add browser controls, selection counts and folder badges.
- [x] Validate persistence, execution, analysis and GUI behavior with focused tests and environment Pyright.
- [x] Update user documentation and record validation results here.

## Implementation notes

- `workflows/experiments/exclusion.py` owns active-state filtering, folder selection and saved inclusion changes. Discovery continues to return excluded experiments.
- Inclusion changes use the existing run writer lock. Browser selections are deduplicated, and actions are disabled while processing. Adopted migration checkpoints must be fully rebuilt before inclusion changes are available.
- Excluded siblings are skipped when an acquisition is reconverted. Their state and individual outputs remain unchanged. Per-series history restoration also retains the current inclusion choice.
- The artifact checker omits excluded series from processing conflicts. Raw acquisitions with all known series excluded are omitted from conversion checks. Compaction and full-rebuild planning use active states.
- Master Parquet schema metadata records active membership using existing artifact revision stamps and portable series names. Condition-folder movement remains a paths/tags update. Older unstamped masters retain all-active behavior until an explicit exclusion requires rebuilding.
- Master-only rebuilds use the existing Manage files action, including for compacted experiments. They reaggregate valid measurements without processing images. Missing or outdated active measurements enter the existing numerical rebuild planner first. Conversion-only launches defer analysis rebuilds.
- User instructions are documented in `docs/user_guide/runs_and_settings.md` and `docs/user_guide/analysis_and_results.md`.
- Follow-up browser feedback: checker-reported outdated files are amber, including master Parquets, upstream-rerun conflicts and paths/tags warnings. File decoration consumes existing check results and clears when they are resolved.
- Per-series analysis conflicts also propagate to existing master tables, so an upstream rerun highlights both the affected analysis Parquet and its combined table before those files are regenerated.

## Validation

- Runtime/state/analysis regression group: **158 passed**. Covers state/discovery, conversion, batch/conveyor and interactive execution, pipeline/preflight, raw inputs, portable experiments, file management and both analysis aggregators.
- GUI regression group: **53 passed** using `QT_QPA_PLATFORM=offscreen`. Covers browser selection and badges, real main-window exclusion/re-inclusion, removal/restoration of a master from preserved individual measurements, portable files, navigation and completion reports.
- **211 focused tests passed** across those two groups. The GUI group reports 14 dependency deprecation warnings from Torch; no test failures remain.
- Environment Pyright over changed implementation modules and changed/new tests: **0 errors, 0 warnings**. Interpreter auto-discovery did not resolve the environment, so validation used a temporary configuration with Python 3.12, workspace package sources and environment site-packages explicitly supplied.
- `git diff --check` passed.
- Validation is Linux/offscreen; no native Windows or large-acquisition performance validation was performed.
- Amber-file follow-up: 51 focused browser, portable-file, artifact-check and exclusion tests passed. The main-window integration check publishes an upstream revision, verifies amber on the individual and master Parquets, then verifies that regenerated outputs clear the color. Changed modules and tests pass Pyright with 0 errors and 0 warnings.
