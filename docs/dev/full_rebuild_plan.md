# Optional full rebuilding after migration

Status: implemented and verified locally.

- Migration remains metadata/layout-only by default. Its optional rebuild
  checkbox starts unchecked.
- Checking rebuild in the migration dialog authorizes processing directly after
  migration, without a second full-rebuild review. The standalone rebuild action
  in Manage files retains its explicit review dialog.
- Rebuild all experiment results reruns conversion, previously completed or
  currently enabled steps and their prerequisites as one consistent run workflow.
- Rebuilding can take a long time. Final arrays, masks and measurements may
  change, including small numerical differences with otherwise identical settings.
- Space is checked before starting. A restorable experiment-folder/state backup
  is retained before any numerical output is replaced.
- Existing final images are no longer preserved as active checkpoints during
  reconstruction. They are rebuilt with genuine current input revisions; no
  timestamps or derivation links are forged.
- Successful rebuilding validates normal provenance, saves the rebuilt enabled
  workflow and removes superseded active filenames while retaining their backup.
- Hand-drawn REF/ROI masks retain their pixels and still require alignment review
  if registration changes.
- GUI and interactive CLI use the same review, planning and execution API.

This replaces the earlier partial-intermediate option documented in previous
plans. It does not change migration-only behaviour or backup restoration.

## Validation

- 685 core/workflow/FITS I/O/progress tests passed.
- 18 focused GUI/CLI tests passed, including unchecked migration-only behaviour
  and the checked full-rebuild path with time/result-change/backup warnings.
- Pyright reports zero errors or warnings for the reviewed code; whitespace checks pass.
- Synthetic tests rebuild registration, final arrays, segmentation, tracking and
  measurements with real metadata publication; the ordinary checker reports no
  remaining provenance conflicts. Original files remain byte-identical in backups.
- Multi-series rebuilding and restoration after an injected numerical failure pass.
- Numerical segmentation/tracking backends were mocked; native Windows, real ND2
  and GPU processing were not exercised.
