# Git and submodule cheatsheet

FITS records each submodule as a repository URL in `.gitmodules` plus an exact
commit in the parent repository. Updating files inside a submodule and updating
the commit recorded by FITS are therefore two separate commits.

## Clone FITS

```bash
git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits
cd fits
uv sync
```

If FITS was cloned without its submodules:

```bash
git submodule update --init --recursive
uv sync
```

## Inspect submodules

```bash
git submodule status
git status
git -C bioimagequant status
git diff --submodule=log
```

A leading `-` in `git submodule status` means the submodule is not initialized;
`+` means its checked-out commit differs from the commit recorded by FITS.

## Restore the versions recorded by FITS

Use this after switching or pulling a FITS branch:

```bash
git submodule sync --recursive
git submodule update --init --recursive
uv sync
```

This checks out the exact submodule commits recorded by the current FITS
commit. It does not update them to the newest upstream revisions.

## Pull FITS and its recorded submodule versions

```bash
git pull --recurse-submodules
git submodule update --init --recursive
uv sync
```

## Work on a submodule

Enter the submodule, work on a branch, and commit/push there first:

```bash
cd bioimagequant
git switch main
git pull
git add src tests README.md
git commit -m "Describe the submodule change"
git push
cd ..
```

Then record that new submodule commit in FITS:

```bash
git add bioimagequant
git commit -m "Update bioimagequant"
git push
```

Do not leave important work only as “modified content” inside a submodule: the
parent repository records the submodule commit, not its uncommitted files.

## Update submodules from their configured remote branches

```bash
git submodule update --remote
git status
git diff --submodule=log
```

Review the resulting revisions, run the tests, then commit the changed
submodule pointers in FITS. Add `--recursive` only if nested submodules are ever
introduced.

## Add a submodule

```bash
git submodule add https://github.com/OWNER/REPOSITORY.git package_name
git add .gitmodules package_name pyproject.toml uv.lock
git commit -m "Add package_name submodule"
```

Also add the package to `[tool.uv.workspace].members`, register it under
`[tool.uv.sources]`, and run `uv lock` or `uv sync` as appropriate.

## Remove a submodule

First commit or push anything worth keeping inside the submodule. From the FITS
root:

```bash
git submodule deinit -f package_name
git rm package_name
rm -rf .git/modules/package_name
git commit -m "Remove package_name submodule"
```

Also remove its uv workspace/source/dependency entries and refresh `uv.lock`.
The `rm -rf` command deletes Git's local cached copy of that submodule, so check
the path carefully and use it only after preserving any work you need.

## Change a submodule URL

Edit `.gitmodules`, then run:

```bash
git submodule sync --recursive
git submodule update --init --recursive
git add .gitmodules
git commit -m "Update submodule URL"
```

## Useful recovery commands

Return one submodule to the commit currently recorded by FITS:

```bash
git submodule update --checkout package_name
```

Show the recorded commit and the submodule's current commit:

```bash
git ls-tree HEAD package_name
git -C package_name rev-parse HEAD
```

Before any cleanup, inspect both levels:

```bash
git status
git submodule foreach --recursive 'git status --short'
```
