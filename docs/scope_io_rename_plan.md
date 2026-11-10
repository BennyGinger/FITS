# ScopeIO rename and integration checklist

## Agreed scope

Pass 1 develops and validates the I/O library independently on a branch. Pass 2
integrates it with FITS and its companion repositories after the user switches
to the reviewed branch and authorizes integration. The existing FITS checkout,
environment, experiment files, and consumer code remain on the current library
during pass 1. No remote repository is renamed or published in pass 1.

Names: repository/folder/import `scope_io`, distribution `scope-io`, public
class `ScopeIO`, metadata container `ImageMetadata`, metadata member/key
`artifact`, and metadata update method `with_artifact()`.

The historical serialized `fits_io` key remains readable. New writes use
`artifact`. TIFF tag number 65000 remains unchanged under a neutral constant
name. Historical producer identities and revisions are preserved; FITS/FISH
workflow filenames and directories are outside this library-only pass.

## Pass 1 — independent library branch

- [x] Record starting commits and working-tree status; preserve existing work.
- [x] Create `refactor/scope-io` in the I/O repository from `a8b831e`, using an
      isolated worktree so the active FITS submodule checkout stays on `main`.
- [x] Run the original library tests and record baseline type diagnostics.
- [x] Rename the Python package and public API; update internal imports,
      annotations, exports, docstrings, logger names, tests, and documentation.
- [x] Add backward-compatible reading of the old metadata key; write the new
      neutral key and define/test handling when both keys are present.
- [x] Rename the distribution, metadata version lookup, and package description;
      remove the stale CLI entry point that targets a nonexistent `main`.
- [x] Add meaningful compatibility/round-trip tests for pixels, axes, channel
      identity, calibration, timings, overlays, custom metadata and provenance.
- [x] Run the full standalone library suite and Pyright; fix diagnostics in
      changed code and record any remaining limitations accurately.
- [x] Build wheel and source archive; smoke-test the wheel independently of the
      editable library without changing FITS's installed environment.
- [x] Commit the reviewed library changes on the branch; record the commit,
      validation results and exact switch/integration instructions below.
- [x] Release the temporary worktree after committing so the user can switch
      the existing submodule checkout to the branch normally.

## Pass 2 — integration authorized 2026-11-10

- [x] Switch the I/O checkout to `refactor/scope-io` after authorization and
      integrate its breaking Python API with the consumers.
- [x] Create integration branches in FITS, `stackalign`, and `tracklink`,
      preserving any unrelated local work.
- [x] Update their imports, API calls, type annotations, examples and tests.
- [x] Update FITS's dependency/version identity, logger names, workspace/test
      paths, documentation and generated uv lockfile.
- [x] Add FITS producer-name compatibility for `fits-io` and `scope-io` so old
      conversion provenance does not prevent continued processing.
- [x] Update FITS's direct serialized metadata readers/rewriters, TIFF/Parquet
      provenance and viewers to accept the historical and neutral keys.
- [x] Verify historical files, conversion reruns, processing, quantification,
      viewers and backups; no bulk experiment migration should be necessary.
- [x] Rename the existing remote library repository to `scope_io` while keeping
      its history; rename the local submodule path and update `.gitmodules`
      and remote references. Do not create a replacement Git history.
- [x] Commit companion repositories before updating FITS's submodule pins.
- [x] Build the integrated distributions, synchronize the shared environment and
      run startup/update/process checks. Record limits on cold installation,
      publication and rollback separately below.

## Starting state

- Library: `fits_io`, branch `main`, commit `a8b831e`; working tree clean.
- Parent FITS: existing unrelated edits are present and must be preserved.
- Package version before rename: `2.2.0`.
- No experiment data will be rewritten during this work.

## Validation and handoff

Validation date: 2026-11-09. Library version on the branch: **3.0.0**, reflecting
the breaking Python API. Nothing has been published or tagged.

| Check | Result |
| --- | --- |
| Original standalone test suite | 189 passed |
| Renamed library, including new compatibility tests | 200 passed |
| Same suite imported from the installed wheel in a temporary target | 200 passed |
| Pyright, all library source and tests | 0 errors, 0 warnings |
| Original type-check baseline | 20 errors in four test files; corrected on the branch |
| Wheel and source archive | Both built successfully using `uv build` |
| Wheel identity | `scope-io` 3.0.0, `scope_io` import, public exports and `py.typed` verified |
| Real ND2 samples | Eight files: axes, shape, channel count, channel colors and first YX plane match the original library |
| Real source preservation | ND2 source sizes and modification timestamps unchanged |
| Active FITS environment | Original `fits-io` 2.2.0 remains installed; `scope_io` is not installed there |

Pylance diagnostics are not exposed in this session. Pyright was run using a
temporary configuration explicitly pointing at the existing shared FITS `.venv`;
the separate worktree's automatic interpreter discovery did not locate those
dependencies. No extra project virtual environment was created. The branch
also declares Pyright in its dev dependencies and provides project settings.

Compatibility tests exercise old/new metadata keys, matching and conflicting
duplicate keys, producer/version history, revision preservation, signed float32
pixels, channel lineage, calibration, timing, custom metadata, overlays and
metadata-only rewriting without changing encoded pixel segments. A historical
producer's known version survives even when its old distribution is uninstalled.

The numeric TIFF tag stays 65000. The old import/API aliases are intentionally
absent. Conflicting old/new metadata keys raise an error. The default library
output filename is now neutral `array.tif`; caller-selected filenames stay under
the caller's control. The obsolete, broken CLI entry point is removed.

These checks were run on Linux. Native Windows behavior, the later FITS
integration, and legacy/RGB ND2 variants are not established by these checks.
The eight real ND2 comparisons read headers and one plane per file, not complete
large stacks. No real experiment was migrated or rewritten.

Ready library branch: **`refactor/scope-io`** in the existing `fits_io` repository.
Commit: **`90a3754415a3c9458ccc9b0cba0e87cb2efd426b`** —
`Rename fits-io to ScopeIO with neutral artifact metadata`.
Its ancestor is the original `a8b831e` commit; existing history is retained.
The temporary worktree has been removed, leaving this branch available to switch
to. The active library checkout remains clean on `main` at `a8b831e`.

When the user is ready for pass 2, from the FITS repository root:

```bash
git -C fits_io switch refactor/scope-io
```

This changes only the library checkout. FITS still has old imports, dependency
names and metadata consumers until pass 2 is implemented; it cannot use the new
library API yet. Complete integration before launching FITS or synchronizing the
parent uv workspace against the renamed package. To return to the original
library before integration, use `git -C fits_io switch main`.

The library suite can be rerun with the existing shared interpreter before the
parent workspace is integrated:

```bash
PYTHONPATH="$PWD/fits_io/src" .venv/bin/python -m pytest -c fits_io/pyproject.toml fits_io/tests -q
```

Temporary distribution artifacts are under `/tmp/fits-scope-io-dist/`:
`scope_io-3.0.0.tar.gz` and `scope_io-3.0.0-py3-none-any.whl`. These artifacts and
temporary validation outputs are not committed and may disappear on reboot.

Pass 2 remains pending. No consumer repository, submodule pin, remote URL or
remote repository name was changed in pass 1.


## Pass 2 results — 2026-11-10

The active FITS branch is `refactor/scope-io-integration`. The active I/O
checkout is now `scope_io/` on `refactor/scope-io` at `90a3754` (3.0.0).
The existing I/O Git database was preserved; its internal administrative path
may still contain the historical name. The GitHub repository was renamed by
its owner to <https://github.com/BennyGinger/scope_io>; `.gitmodules` and the
local remote now use that URL.

Companion integration commits:

- `stackalign`: `a392fec`, branch `refactor/scope-io-integration`.
- `tracklink`: `b599ddd`, branch `refactor/scope-io-integration`.

FITS now imports ScopeIO, uses `ImageMetadata.artifact` and `with_artifact()`,
and normalizes historical TIFF/Parquet metadata through ScopeIO before updating
path references. The serialized Parquet envelope `fits_artifact` remains an
application-owned format identifier. Historical `fits-io`/`fits_io` producer
names are equivalent to `scope-io`; unrelated producers still raise an error.
Existing producer/version history is preserved when appending channel metadata.

The uv workspace, test paths, dependency identity, logger names, documentation
and lockfile use ScopeIO. `uv sync --offline --frozen` successfully replaced
`fits-io` 2.2.0 with `scope-io` 3.0.0 in the existing shared environment. Startup
verification explicitly imports ScopeIO. No new virtual environment was made.
The main application remains FITS 4.1.0; its own rename/release is separate.

| Check | Result |
| --- | --- |
| Integration-only index snapshot, excluding unrelated local edits | 37 conversion/metadata/file-management/compatibility tests passed |
| New FITS legacy compatibility tests | 5 passed; old-key conversion overwrite and old/new Parquet provenance verified |
| Broad FITS non-GUI/non-startup suite, excluding location tests | 550 passed; 2 existing failures reproduced before integration |
| Conversion, metadata, file management, locations, artifact checks, execution and I/O tests | 248 passed; 2 existing failures reproduced before integration |
| `stackalign` and `tracklink` suites | 222 passed |
| File-management, lineage and channel-conversion GUI group | 42 passed |
| Raw viewer, mask preview and tracking overlay GUI group | 42 passed |
| Information, real pipeline-process and startup group | 110 passed; 2 existing layout failures reproduced before integration |
| Changed production code and new compatibility tests, Pyright | 0 errors, 0 warnings |
| Full mechanically changed-file type audit | 468 existing errors versus 472 before integration; no new diagnostic signatures |
| Existing Run3_test data | 36 existing artifacts read; source sizes/modification times unchanged |
| Real tuner discovery | 26 passed; 4 pre-existing mocked routing cases deselected |
| Full startup verifier | Imports, existing model-cache writability and CUDA detection passed |
| FITS wheel/source archive | Both built successfully |
| Shared environment installation | Frozen/offline sync succeeded |

Test groups overlap; do not add their counts as unique tests. The type baseline
was reconstructed from the original application/library plus the pre-integration
working-tree snapshot. Four old smoke-script type errors were corrected by
using the current array and save APIs.

Existing failures are outside this rename:

- Required-rebuild planning enables Quantification without an included mask
  producer in one location-check scenario.
- Removed-experiment and invalid-master tests still expect the old location-update
  path, whereas current code routes these through analysis rebuilding.
- Channel-tools and mask-panel tests expect previous button labels/layouts.

Each reported failure was reproduced with the original library and code before
the integration edits. The mocked main-GUI tuner-routing tests also block on a
modal interaction before and after integration; those were stopped with a time
limit. All 26 real tuner-discovery checks passed. Native
Windows and a cold machine without the cached dependencies remain unvalidated.

Pre-existing local edits were retained. The integration changes are staged and
committed separately, using the original tracked-file contents for any files
that also had unrelated edits. The original working-tree diff and untracked
snapshot were retained under `/tmp/fits-before-scope-integration*` for this run.
No real experiments were migrated or rewritten.

The integration branches are local; no branches have been pushed, no default
branches merged, and no release tags or packages published. A fresh clone from
GitHub cannot use the new local pins until those commits are published. This is
separate from renaming the GitHub repository, which is complete.

Rollback now involves both code and environment: use the original branch/pins,
restore the `fits_io` checkout path and run uv sync with the old lockfile. Old
application versions do not understand newly written `artifact` metadata; Git
rollback alone does not convert those files back. Keep their backups if old
application compatibility is needed. The updated application reads both keys.
