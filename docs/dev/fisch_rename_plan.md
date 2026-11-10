# FITS to FIScH: coordinated rename, migration and release

Status: planning agreed; application implementation has not started.
Updated: 2026-11-10.

## Agreed identity and scope

- Display name: **FIScH**.
- Expansion: **Fluorescent Imaging and Single-cell Histories**.
- Repository, Python distribution and import: **`fisch`**.
- Command prefix: **`fisch`** / **`fisch-*`**.
- Processed scientific outputs: **`proc_*`**.
- Run metadata directory: **`.pipeline`**.
- Acquisition metadata directory: **`.acquisition`**.
- Include the reviewed existing local changes in the coordinated release.
- Release ScopeIO 3.0.0 and the renamed application together; bump the
  application once. ScopeIO integration is recorded separately in
  [the ScopeIO checklist](../scope_io_rename_plan.md).
- Preserve the existing Git histories. Rename repositories rather than creating
  replacement repositories with new histories.
- This document authorizes no code, repository, installation or data changes by
  itself. Implementation follows the user's subsequent instruction.

## Installed commands and imports

Available commands and imports follow the distributions installed in the chosen
Python environment. The `fits` and `fisch` names do not inherently conflict;
both could exist if both distributions were installed. The rename will install
the new distribution and update its consumers and OS shortcuts. There is no
requirement for old import aliases or command redirects.

The release will use only the new Python API and command names. Legacy
experiment support is independent of retaining old executable/import names.
Environment synchronization must remove the obsolete managed editable package
and its entry points when replacing it with the renamed application.

## Compatibility and processing policy

- Use one application-version compatibility threshold: the first FIScH release,
  **5.0.0**, confirmed by the user.
- Do not introduce a separate storage-schema version for this rename. Retain
  structured metadata/lineage validation alongside the application threshold.
- All FITS-era experiments need migration, whether pre-4 or post-4. They share
  one migration target and one user-facing migration workflow.
- Keep readers/adapters for the actual historical layouts and metadata schemas,
  including pre-4. Increasing the write threshold must not remove those readers.
- A run containing legacy active experiments is read-only and processing is
  blocked. The same shared rule applies to GUI, CLI and direct pipeline entry
  points. GUI explains migration; CLI fails before producing outputs.
- Legacy viewers may inspect data. Editors, mask/track saves, tuning writes,
  compaction and other run mutations are blocked until migration. Read-only
  previews use temporary caches outside the legacy run when necessary.
- Legacy compacted experiments require migration **and rebuilding from original
  acquisitions** before processing is enabled. Renaming cannot restore removed
  intermediates. Missing originals block rebuilding.
- Ordinary complete experiments receive naming/metadata migration without
  recomputing valid scientific results. Existing reconstruction requirements for
  older/incomplete inputs still apply when their required data is unavailable.
- Post-4 structured lineage remains valid history and must be preserved when
  rebinding names. Pre-4 missing lineage is recorded as unavailable; do not
  fabricate earlier processing revisions or discard known post-4 lineage merely
  because both fall below the new version threshold.

## Central naming responsibility

Use one focused naming module under the application environment/path layer.
Give it a clear **current/default** convention and **legacy aliases**. Keep
workflow definitions separate from filenames. Move applicable constants from
`environment/constant.py` and literal names elsewhere into this naming layer.

Discovery, the checker, viewers, steps, extraction, compaction, rebuild, reset,
backups and migration obtain names through that layer. Legacy adapters resolve
old names at discovery/read/migration boundaries; numerical processing does not
contain scattered legacy filename tests. Include current and legacy internal
directories in history exclusions so backups never become active experiments.

Bootstrap scripts must remain usable outside the application environment. Keep
bootstrap identity/path definitions dependency-free; do not import the full
installed application merely to obtain a shortcut or log filename. Avoid
duplicated literal names within the runtime or bootstrap naming responsibilities.

## Application, repository and command table

| Current | Target / treatment |
| --- | --- |
| FITS | FIScH |
| Fluorescent Image Tracking Software | Fluorescent Imaging and Single-cell Histories |
| Main repository `fits` | Rename existing repository to `fisch`, retaining history |
| Distribution and import `fits` | `fisch` |
| Source package `src/fits/` | `src/fisch/` |
| `fits` | `fisch` |
| `fits-gui` | `fisch-gui` |
| `fits-segtune` | `fisch-segtune` |
| `fits-regtune` | `fisch-regtune` |
| `fits-bgtune` | `fisch-bgtune` |
| `fits-trackedit` | `fisch-trackedit` |
| `fits-drawmask` | `fisch-drawmask` |
| `fits-trackviewer` | `fisch-trackviewer` |
| `fits-channel-labels` | `fisch-channel-labels` |
| Package imports, qualified patch targets, subprocess module arguments | Update to `fisch` |
| Distribution version lookups | Look up `fisch` for new application records |
| Application-facing classes and strings | FIScH terminology; generic metadata/path helpers use responsibility-based names |
| `FitsMeta`, `metadata/fits.py` | Prefer neutral pipeline metadata names; update imports and tests together |
| `FITS_*` naming constants, `fits_dir`, `ensure_fits_directory` | Neutral names in central naming/path helpers |
| README, developer/user guides, code examples and screenshots | Update visible names and commands; preserve explicitly labelled historical explanations |
| ScopeIO and other companion distributions | Keep their identities; change application references only where needed |
| pyproject, uv workspace/configuration, generated lockfile, type/test paths | Update and validate together |

## Scientific outputs and experiment paths

| Current | Target / treatment |
| --- | --- |
| `fits_array_raw.tif` | `proc_array_raw.tif` |
| `fits_array_reg_channel.tif` | `proc_array_reg_channel.tif` |
| `fits_array_reg.tif` | `proc_array_reg.tif` |
| `fits_array_bgsub.tif` | `proc_array_bgsub.tif` |
| Compacted `fits_array.tif` | `proc_array.tif`; legacy compacted runs also require rebuilding |
| Earlier uncompacted `fits_array.tif` | Interpret recorded stage/layout, then adopt/rebuild appropriately; do not blindly classify as compacted |
| `fits_masks_seg.tif` | `proc_masks_seg.tif` |
| Earlier `fits_mask.tif` | Legacy alias for segmentation; normalize to `proc_masks_seg.tif` |
| `fits_masks_track.tif` | `proc_masks_track.tif` |
| Earlier `fits_track.tif` | Legacy alias for tracking; normalize to `proc_masks_track.tif` |
| Compacted `fits_masks.tif` | `proc_masks.tif`; legacy compacted runs also require rebuilding |
| `fits_track_edited.tif` | `proc_track_edited.tif` |
| `fits_track_edited_filtered.tif` | `proc_track_edited_filtered.tif` |
| Compartment masks ending `_mb.tif` / `_cyto.tif` | Corresponding current `proc_*` stem and existing compartment suffix |
| `fits_ref_{label}.tif` | `proc_ref_{label}.tif` |
| `fits_roi_{label}.tif` | `proc_roi_{label}.tif` |
| `fits_track_overlay*` exports | `proc_track_overlay*` |
| `fits_quantification.parquet` | `proc_quantification.parquet` |
| `fits_distance_profile.parquet` | `proc_distance_profile.parquet` |
| `master_quantification.parquet` | Keep generic name |
| `master_distance_profile.parquet` | Keep generic name |
| `.fits/` | `.pipeline/` |
| `.fits_experiment/` | `.acquisition/` |
| `fits_settings.toml` | `settings.toml` under `.pipeline/` |
| `fits_settings_{timestamp}.toml` | `settings_{timestamp}.toml` in settings history |
| `.fits_settings.*` temporary settings files | Neutral settings temporary prefix |
| `experiment_state.json`, `experiment_state/`, `cache/`, `tuning/`, `backup/` | Keep generic names inside the new metadata roots |
| `upgrade_pending.json`, transaction and geometry-review records | Keep generic names; relocate and update their managed references |
| Original acquisitions and user condition/acquisition/series names | Preserve names and bytes |
| User-chosen external paths/filenames | Do not rename by substring replacement |

## Metadata, tables and provenance

Parquet schema metadata is descriptive information stored beside the table,
not a measurement column. The old `fits_artifact` key identifies the JSON
artifact/provenance block. Renaming it does not rename or modify intensity
columns or numerical measurements.

| Current field / information | Target / treatment |
| --- | --- |
| Parquet schema key `fits_artifact` | `pipeline_artifact`; legacy read alias |
| Master schema key `fits_active_experiments` | `pipeline_active_experiments`; legacy read alias |
| Historical image metadata key `fits_io` | Read through ScopeIO; migrated writes use `artifact` |
| Current image metadata key `artifact` | Keep |
| TIFF tag 65000 | Keep its numeric identity |
| `pipeline_meta`, `steps`, `custom_metadata` | Keep generic keys |
| Active compatibility version | First FIScH release threshold; migration records adoption into this version |
| New application producer identity | `fisch`, with its actual version |
| Historical producer names/versions and scientific step timestamps | Preserve in retained provenance and migration history; no blanket text replacement |
| Migration `original_scope_io` / historical equivalent | Neutral `original_artifact`; accept existing historical migration records |
| Tracking-edit `fits_version` | `pipeline_version`; historical read alias |
| State JSON `artifacts` paths and `series_path` | Rebind managed renamed paths; preserve unchanged series identities |
| `derived_from[].artifact_path` | Rebind; preserve known `created_at` revisions for naming-only migration |
| ImageJ information summaries | Refresh the human-readable metadata consistently with the migrated payload |
| Table path columns, where present: `image_path`, `mask_path`, `artifact_path`, `source_path`, `experiment_path` | Update managed references only |
| `experiment_id`, `cell_id`, `condition_level_*` | Preserve when acquisition/series identities and conditions are unchanged |
| `object_name`, `object_channel`, labels, frames, coordinates and regions | Preserve scientific semantics and values |
| Intensity, shape, motion and distance measurements | Preserve during naming-only migration |
| Master membership/revision metadata | Rebind stored references while preserving unchanged membership and result revisions |
| Saved protocols/settings with application-owned paths | Update managed path references, preserving user parameters and external paths |
| Exclusion flags, manual edits and REF/ROI encodings | Preserve; retain alignment review requirements if rebuilding changes geometry |

## Launch, setup, updater, reports and runtime support

| Current | Target / treatment |
| --- | --- |
| `startup/setup.py`, `launcher.py`, `updater.py`, `verify.py`, `state.py`, `locking.py`, `shortcuts.py`, `update_dialog.py` | Keep generic filenames; update imports, subprocess commands, branding and repository references |
| `install_linux.sh`, `install_win.bat`, `install_macos.sh` | Keep generic filenames; update installation identity/messages |
| `startup/install_unix.sh`, `install_uv.ps1` | Keep generic names; neutral internal installer function/temp names |
| `startup/launch_linux.sh`, `launch_macos.sh`, `launch_win.bat`, `launch_win.vbs`, `windows_shortcut.ps1` | Keep generic names; launch the new package/commands |
| `FITS_APPLICATION_LOCK`, `FITS_UPDATE_CONSOLE`, `FITS_INSTALL_ROOT`, `FITS_REFRESH_SHORTCUTS`, `FITS_BOOTSTRAP_PYTHON` and other application-owned `FITS_*` variables | Corresponding `FISCH_*` names; update every reader and writer together |
| `fits.desktop` | `fisch.desktop` |
| Windows `FITS.lnk` | `FIScH.lnk` |
| macOS `FITS.command` | `FIScH.command` |
| Application name, desktop ID, WM_CLASS/dock integration and shortcut descriptions | Consistent FIScH identity |
| `fits_icon.png`, `fits_icon.ico`, `fits_logo.png`, `fits_title.svg` and active references | FIScH asset names and visible wordmark; preserve/review the artwork deliberately |
| Cached installed icon names `fits-{hash}.png` | Corresponding `fisch-{hash}.png`; refresh managed old shortcuts/icons |
| Run logs `fits_{timestamp}.log` | `run_{timestamp}.log` beneath `.pipeline/logs/` |
| Run reports `fits_report_{timestamp}.txt` | `report_{timestamp}.txt` beneath `.pipeline/reports/` |
| Log handler names such as `fits_console` / `fits_file` | Neutral pipeline handler names |
| `startup/logs/install.log`, `update.log` | Keep generic names |
| `installed.json`, `update-pending.json`, `update-result.json`, `application.lock` | Keep generic filenames; update embedded identity/path data as necessary |
| Run `run_write.lock` | Keep generic name under the new metadata root |
| `fits-viewer-cache`, segmentation-tuning and compaction temporary prefixes | Neutral pipeline cache/temporary names; regenerate disposable caches when appropriate |
| Git remotes, updater fetch targets, install instructions and receipts/signatures | Update without losing history; preserve startup repair/update behavior |
| Reset-to-raw and file-management discovery | Recognize the appropriate current/legacy conventions and protect original acquisitions |

## Whole-run migration and restoration rules

Any remaining legacy file among active experiment data keeps the whole run
blocked, and migration remains available. This also covers interrupted migration
or manual partial renaming: already migrated files do not make the remaining
legacy files writable. Migration must recognize and finish the remaining work.
Historical files inside retained backups are excluded from this active-data
test. Compacted legacy runs additionally remain blocked until required
rebuilding succeeds.

Mixed names are a blocked legacy state, not an additional processing mode.
Plan the whole run before mutation; report ambiguous duplicate targets without
overwriting either file. Keep migration/recovery accessible rather than treating
partial renaming as an unsupported run. Close readers/editors and acquire the
existing run writer lock before applying changes. Use the existing
snapshot/transaction facilities rather than inventing a second migration system.

- Retain a restorable snapshot before modifying active data.
- Rename all active application-managed outputs and metadata roots, update
  references/headers/state/tables, and validate the resulting run together.
- Do not mark the migration complete or lift the Run block prematurely.
- Naming/metadata failure rolls back the transaction. Numerical rebuilding may
  be lengthy: retain a durable pending state and the original snapshot, and
  resume required rebuilding or explicitly restore the snapshot after failure.
- Existing and newly retained backups retain their historical contents. Moving
  the enclosing backup directory does not mean rewriting the snapshot's inner
  filenames, metadata or original acquisition copies.
- Restoring a historical snapshot returns that run to legacy read-only status
  until it is migrated again.
- Retain both legacy and current history exclusions in discovery.
- Preserve raw originals and REF/ROI/manual data; review geometry after a rebuild
  if registration changes, rather than silently declaring drawings aligned.

## Execution checklist

1. [x] Confirm the application release/compatibility threshold: **5.0.0**.
2. [x] Review and checkpoint all intended local changes, submodules first and
       then the parent repository/pins. Record the starting branches and commits.
3. [ ] Create the FIScH rename branch from the tested, complete ScopeIO integration,
       using the current checkout and shared environment. Preserve the main
       branch and the named FITS rollback checkpoint; do not merge the FIScH
       rename until validation and review.
4. [ ] Implement the central current/legacy naming conventions and preservation tests.
5. [ ] Rename the source package, distribution, imports, commands and GUI identity.
       Apply the single confirmed application-version bump on this branch so
       new records already carry the target version during migration testing.
6. [ ] Update launch/setup/updater/scripts/shortcuts/assets/configuration together.
7. [ ] Apply the new threshold and shared whole-run read-only/Run-block policy,
       retaining historical readers and the single migration entry point.
8. [ ] Implement complete active-file/folder/metadata/table migration with backup,
       collision checks, rollback and pending-rebuild handling.
9. [ ] Update compaction, rebuilding, reset, extraction, editors and viewers to
       use the central names and honor migration/read-only status.
10. [ ] Test pre-4 and FITS-4 runs, compacted runs, missing originals, restored
        backups, failed/interrupted migration and existing REF/ROI/manual edits.
11. [ ] Run scientific preservation, GUI/CLI, startup/install/update, package-build
        and type checks; distinguish baseline failures from rename regressions.
12. [ ] Manually verify old-run viewing/migration and a new end-to-end FIScH run.
13. [ ] Rename the existing main remote repository and update remotes/instructions.
14. [ ] Verify that the single application-version bump matches the compatibility
        threshold; keep the prepared ScopeIO 3.0.0 identity. Do not bump again
        merely for merging or integration.
15. [ ] Publish dependency commits before the application pins, validate a fresh
        checkout and an existing-install update, then tag/release both together.

## Branch, merge and rollback policy

The user does not need to run FITS while FIScH is developed. A separate worktree
or validation environment is therefore unnecessary. Use a refactor branch in the
current checkout and the shared `.venv`. Main retains the working FITS source;
the editable installation may be temporarily unusable during development.

First merge the tested ScopeIO integration and the reviewed local feature/test
changes into the normal branches. The pre-merge heads are retained as
`safety/pre-scopeio-merge` in each affected repository. Record the post-merge
working FITS application as `safety/fits-before-fisch` in the parent repository.
That parent commit records all dependency pins. No FIScH implementation begins
as part of this preparatory merge.

Rollback to the working FITS checkpoint, after preserving any new uncommitted
refactor work, consists of:

```bash
git switch safety/fits-before-fisch
git submodule sync --recursive
git submodule update --init --recursive
uv sync --frozen
```

Do not discard uncommitted work or use a destructive reset to perform rollback.
Switching branches alone does not restore the environment. The existing FITS
launch scripts/shortcuts may also need reinstalling if the FIScH refactor has
already replaced them. Keep the checkout location stable during development.

Testing migrated data uses copied experiments. Code/environment rollback does
not undo data migration: restore the retained experiment backup separately if
old FITS must open a migrated run. The old application must not be expected to
read newly migrated data.

The application release and compatibility threshold are confirmed as 5.0.0.
No separate schema-version decision or old-command redirect is required.


## ScopeIO merge checkpoint — 2026-11-10

The integration and the reviewed local feature/test commit `1a6a292` have been
fast-forwarded into FITS `main`. ScopeIO is on `main`; stackalign uses its
existing default branch `master`; tracklink is on `main`. No FIScH source rename
has started. These are local merges; nothing was pushed or released by this step.

| Repository | Normal branch | Pre-merge rollback branch |
| --- | --- | --- |
| FITS | `main` | `safety/pre-scopeio-merge` at `d9ef9f6` |
| ScopeIO | `main` | `safety/pre-scopeio-merge` at `a8b831e` |
| stackalign | `master` | `safety/pre-scopeio-merge` at `61c90e9` |
| tracklink | `main` | `safety/pre-scopeio-merge` at `b2465aa` |

The parent `safety/fits-before-fisch` branch records the complete validated FITS
state, including its ScopeIO and companion pins and this plan. Use it for the
future FIScH rollback procedure above. The frozen shared environment sync
succeeded on the merged main branch.

A combined test run exposed an explicit `conftest` import collision between
submodules. ScopeIO's filesystem tests now use their scoped pytest reader fixture
instead of importing another module named `conftest`; application code is unchanged.
The changed test file passes Pyright with zero errors/warnings. The combined
ScopeIO/FITS-compatibility/stackalign/tracklink run passed 427 tests; the real
pipeline-process suite passed another 5 tests. All merge working trees are clean
at handoff, with the shared environment synchronized to the recorded lockfile.
