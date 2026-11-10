# Releasing FITS

The package version, Git tag, and version recorded in new pipeline artifacts
use the same number, for example `4.2.0`. Release tags have no `v` prefix.

## Publish a new release

1. Finish the changes and run the processing/GUI tests appropriate to them.
2. Set `[project].version` in `pyproject.toml` to the next stable `X.Y.Z` version.
3. Run `uv lock` so FITS's entry in `uv.lock` has the same version.
4. Commit both version files with the code you want to release, then push to `main`.

The **Release version bumps** GitHub Action tests the release automation, creates
an annotated tag on the exact commit introducing that version to `main`, and
publishes a GitHub Release titled **FITS X.Y.Z**. Later commits in the same push
are not included in that release. A merged branch is released at the merge
commit where the new version first appears on `main`.

Descriptions combine a short list of direct commit subjects with GitHub's
generated release notes and a comparison link. These are automatic change lists,
not AI-written feature summaries. You can edit the release notes on GitHub;
rerunning the workflow preserves those edits. No additional API key is required:
the job uses its built-in `GITHUB_TOKEN` with `contents: write` permission.

The workflow does **not** run the full scientific/GUI test suite or install FITS's
large model dependencies. It runs the release-automation tests and checks the
version files. Validate the application before committing a release bump.

Ordinary commits without a version change do not create releases. Development,
alpha, beta and release-candidate versions (such as `4.2.0.dev0` or `4.2.0rc1`)
are skipped; a subsequent final `4.2.0` bump is published. Stable versions must
increase, and existing tags are never moved or overwritten.

## Retry and inspect

If a run fails after pushing its tag, rerun it from GitHub's Actions page or use
**Release version bumps → Run workflow** on `main`. The workflow resumes missing
releases without recreating published ones. An existing draft/prerelease for the
same stable tag requires manual review rather than being published silently.

Every run checks version changes after the existing `4.1.0` tag. This catches
multiple bumps in one push and missing releases from earlier interrupted or
superseded runs, while leaving the three historical releases untouched.
The workflow runs only for `BennyGinger/FITS` on `main`.

Preview the release plan locally without creating tags or accessing GitHub:

```bash
.venv/bin/python .github/scripts/release.py
```

Run the standalone automation tests without installing FITS or its submodules:

```bash
python -m unittest discover -s tests/releases -v
```

The action takes effect once its files are pushed to `main`. The desktop updater
checks GitHub's latest published stable release and offers its exact tagged
commit. Ordinary commits after that tag are excluded until another release is
published. Existing installations need the release-aware updater code installed
once before their startup checks follow releases.
