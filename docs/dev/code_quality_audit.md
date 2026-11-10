# Recent workflow and artifact code audit

Status: completed; final verification recorded below. No commits or
user-data processing are part of this pass.

## Scope and conventions

The pass covers 79 recently changed production Python files in FIScH and scope_io,
including `workflows/artifacts`, `definitions`, `experiments`, `file_management`,
their runtime/GUI/CLI callers, and the metadata writer. There is no `agents/`
package in this repository; the requested artifact area is `artifacts/`.

- All functions in the reviewed production files have parameter and return
  annotations, with concrete report/state/container types where available.
- Function docstrings use standalone opening/closing triple quotes. Signatures
  and straightforward wrapped calls keep the first argument on the opening line
  and align continuation arguments and the closing parenthesis with it.
- Ordinary local imports were moved to module scope and duplicates consolidated.
  Type-only references remain under `TYPE_CHECKING`. Deliberate deferred imports
  are retained for import cycles, selected viewer/CLI entry points, optional native
  backends, and Parquet-specific Arrow loading.
- Existing tests using fake/empty artifact files now patch dependencies where the
  refactored callers use them. Real-file compatibility and provenance tests retain
  the actual inspectors.

## Responsibility and reuse changes

- Relocation planning separates original acquisition resolution, source grouping,
  artifact path rebinding and metadata-directory moves into typed private helpers.
  Run-level publication delegates per-series updates to a private helper.
- TIFF and Parquet metadata updates share the same path/adoption transform.
- Scoped execution separates running a step from preserving an accepted migrated
  final image while reconstructing earlier intermediates.
- Manage files delegates review of migration, path/tag updates, downstream work,
  drawing alignment and retained-history actions to private helpers. Reviewed
  operations run after the manager closes.
- Compact and Manage files share the responsive file worker/progress dialog.
- CLI compact/manage reuse the GUI application factory. Master-table filenames
  and artifact roles are centralized in FIScH constants.

## scope_io metadata writing

`scope_io/writers/metadata.py` was renamed to `writers/metadata_update.py` and all
callers were updated. It remains in `writers` because it copies and atomically
publishes files; `metadata/` owns payload models, codecs and provenance values.
The writer reuses the existing publish/retry helper. It opens TIFFs in the typed
`r+` mode and reads the guaranteed first page rather than treating every possible
frame as a page with tags. Pixel data remains encoded and unchanged.

## Verification

- Pyright uses the project's virtual environment and the editor's `standard`
  mode. All 79 reviewed production files have zero errors and warnings.
- The full core/workflow/scope_io suite passes: 572 tests. Targeted GUI/CLI,
  navigation, file actions, reports and channel-label tests pass: 101 tests.
- The annotation/docstring inventory, Python compilation and repository/submodule
  whitespace checks pass.
- GUI verification uses Linux/offscreen Qt. Native Windows, real microscopy
  hardware/GPU processing and large ND2 datasets were not exercised.
