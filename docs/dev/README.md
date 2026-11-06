# Developer documentation

Architecture, development procedures, implementation plans, and audit records
for FITS. For practical GUI instructions, start with the
[user guide](../user_guide/README.md). The [project README](../../README.md)
provides the overview, basic installation, and quick usage.

## Architecture and development

- [User-guide screenshot plan](user_guide_screenshots.md): six core figures,
  two optional additions, and capture guidelines for later documentation work.
- [Development setup](development_setup.md): manual environment setup and GPU configuration.
- [Runtime and viewer internals](runtime_and_viewer_internals.md): execution,
  storage, caching, and interactive demonstration details moved from the README.
- [Software credits](software_credits.md): scientific methods, companion libraries,
  supporting dependencies, and citation guidance.
- [Workflow responsibilities](workflow_architecture.md): package boundaries and
  ownership of processing, artifacts, state, and file management.
- [Git and submodule cheatsheet](git_cheatsheet.md): maintaining the FITS checkout
  and its numerical libraries.
- [Development TODOs](todos.txt): completed work and remaining proposals; check
  each item's status before treating it as current behavior.
- [Workflow and artifact code audit](code_quality_audit.md): recorded review
  scope, findings, and validation.

## Artifact and file-management implementation records

These documents record design decisions and implementation progress. They are
not step-by-step user instructions. Later revisions may supersede earlier
decisions; each document retains its existing status and historical notes.

- [FITS 4 artifacts and provenance](fits4_artifacts_plan.md).
- [Portable acquisitions and run status](portable_experiments_plan.md).
- [File-management actions](file_management_actions_plan.md).
- [Compaction, backups, and completion](compaction_backups_completion_plan.md).
- [Optional full rebuilding](full_rebuild_plan.md).

## Tracking development and research

- [µSAM tracking-editor cleanup](microsam_tracking_cleanup.md): integration
  responsibilities and recorded validation.
- [Motion-assisted tracking](motion_assisted_tracking.md): proposed work and
  evaluation directions.
- [Legacy BaxTrack context](baxter_legacy_context.md): historical integration
  details and source retrieval notes.

## User-facing reference

- [Analysis identifiers and measurement columns](../user_guide/analysis_identifiers.md).

## Reference

Existing material moved from the project README; it has not been rewritten into a new walkthrough.

### Repository maintenance

FITS uses Git submodules and a uv workspace. The practical commands for
cloning, updating, editing, adding, and removing submodules are collected in
the [Git and submodule cheatsheet](git_cheatsheet.md).
