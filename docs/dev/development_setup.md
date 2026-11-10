# Development setup

[Developer documentation](README.md)

## Reference

Existing material moved from the project README; it has not been rewritten into a new walkthrough.

### Development environment and GPU configuration

Clone the repository together with its submodules, then synchronize the uv
workspace:

```bash
git clone --recurse-submodules https://github.com/BennyGinger/fisch.git
cd fisch
uv sync
```

### Default GPU setup

Plain `uv sync` and `uv run` select the development defaults automatically:

- Windows x64 is configured for PyTorch 2.8.0+cu129 and torchvision
  0.23.0+cu129 from the CUDA 12.9 package index.
- Linux constrains PyTorch to 2.10.0 and torchvision to 0.25.0 and uses its
  existing package source. The Windows accelerator group does not apply there.

These describe the current dependency configuration, not a hardware validation.
Check GPU availability on the machine where FIScH will run.

No extra flags are needed for everyday development:

```bash
uv run fisch-gui
uv run fisch-segtune
uv run cellpose
```

The shared default is `[tool.uv].default-groups = ["dev", "cuda129"]` in
`pyproject.toml`. To omit the Windows accelerator group:

```bash
uv sync --no-group cuda129
uv run --no-group cuda129 fisch-gui
```

A later plain `uv sync` or `uv run` restores the shared default. The former
`cpu`, `cuda126`, and `cuda128` groups are not defined in the current project.
Omitting `cuda129` removes that group selection; it does not select a dedicated
CPU profile.

Check GPU availability from the FIScH directory:

```bash
uv run python -c "import torch; from cellpose import core; print(torch.__version__, torch.version.cuda); print('Cellpose GPU:', core.use_gpu())"
```

Restart running Python sessions after changing PyTorch, and enable `use GPU`
in the Cellpose GUI (or pass `--use_gpu` to the Cellpose CLI).

## Artifact decisions in direct Python calls

Plain Python callers can pass `artifact_decision(report)` to `start_pipeline`; without a callback,
a required decision raises `PreflightRequired` instead of opening Qt.
