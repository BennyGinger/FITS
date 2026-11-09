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

## Pass 2 — integration, pending user review and authorization

- [ ] User switches the I/O checkout to `refactor/scope-io` when ready. The
      existing FITS application needs consumer changes before it can use this
      breaking Python API; switching only the library is not full integration.
- [ ] Create integration branches in FITS, `stackalign`, and `tracklink`,
      preserving any unrelated local work.
- [ ] Update their imports, API calls, type annotations, examples and tests.
- [ ] Update FITS's dependency/version identity, logger names, workspace/test
      paths, documentation and generated uv lockfile.
- [ ] Add FITS producer-name compatibility for `fits-io` and `scope-io` so old
      conversion provenance does not prevent continued processing.
- [ ] Update FITS's direct serialized metadata readers/rewriters, TIFF/Parquet
      provenance and viewers to accept the historical and neutral keys.
- [ ] Verify historical files, conversion reruns, processing, quantification,
      viewers and backups; no bulk experiment migration should be necessary.
- [ ] Rename the existing remote library repository to `scope_io` while keeping
      its history; rename the local submodule path and update `.gitmodules`
      and remote references. Do not create a replacement Git history.
- [ ] Commit companion repositories before updating FITS's submodule pins.
- [ ] Test clean installation, existing-checkout update and rollback; explain
      separately what Git rollback and data-format backward compatibility cover.

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
