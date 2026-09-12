# FITS

FITS—Fluorescent Image Tracking Software—is a reproducible workflow for
processing and quantifying fluorescence-microscopy experiments. It brings image
conversion, registration, background subtraction, segmentation, tracking,
spatial profiling, and labeled-region extraction into one experiment-aware
pipeline.

The project is aimed at researchers who should not need to write Python to run
an analysis. Its desktop interface exposes pipeline settings and dedicated
viewers for segmentation tuning, reference masks, and ROI masks, while the CLI
supports scripted and repeatable runs. Both use the same settings models and
workflow engine.

## Design

FITS owns experiment discovery, scheduling, state, paths, provenance, and saved
artifacts. Numerical work is delegated to focused submodules that accept arrays
and can also be used independently:

- `fits_io` reads microscopy formats and writes metadata-rich FITS TIFFs.
- `stackalign` performs time-wise and cross-channel registration.
- `bg_sub` removes spatially varying image background.
- `cellpose_kit` provides a stable Cellpose v3/v4 segmentation interface.
- `tracklink` links segmented objects over time.
- `mask_interpolation` completes sparsely drawn reference and ROI masks.
- `bioimagequant` performs object extraction and distance-profile analysis.
- `progress_bar` provides terminal progress and controlled log display.

## Pipeline operation

`fits.pipeline.start_pipeline()` loads the TOML settings, discovers supported
raw images, restores saved experiment state, resolves overwrite decisions, and
runs enabled steps in this order:

```text
Convert → Preprocess → Process → Analysis
           |              |         |
           |              |         └─ distance profile, quantification
           |              └─ segmentation, tracking
           └─ time registration, channel registration, background subtraction
```

Each experiment has an `experiment_state.json` file containing its artifacts,
completed steps, metadata, and provenance. Artifact paths, rather than a second
workflow manifest, are the durable evidence used to resume work. Conversion can
split a raw file into several experiment branches. Re-running an unchanged step
reuses valid output; enabling overwrite rebuilds that step and invalidates the
appropriate downstream work.

The default conveyor execution lets prepared experiments advance while other
experiments are still upstream. In the interactive conveyor, reference/ROI
drawing can overlap with processing, while analysis waits for both its processed
image and finalized mask outcome. A failure is recorded for its experiment and
other experiments continue when possible. Preprocessing or processing failure
skips that experiment's downstream work; a user choosing to omit an optional
analysis input can produce a partial result. If every experiment fails, the
pipeline stops with an error.

Interactive-mask and conversion-only GUI runs write a timestamped log and full
text report under `logs/`. Reports list completed, partial, skipped, and failed
work by phase and experiment. The GUI opens the latest report when a run
finishes; **Full Report** and report files in the directory browser can reopen
it later.

## Development setup

Clone the repository together with its submodules, then synchronize the uv
workspace:

```bash
git clone --recurse-submodules https://github.com/BennyGinger/FITS.git fits
cd fits
uv sync
```

### Default GPU setup

Plain `uv sync` and `uv run` select the development defaults automatically:

- Windows x64 uses PyTorch 2.10.0 and torchvision 0.25.0 with CUDA 12.6,
  verified on the GTX 1080 with NVIDIA driver 576.52.
- Linux keeps its existing PyTorch package source and locked versions. GPU
  support there depends on the Linux machine's GPU and driver; it has not been
  tested from this Windows machine.

No extra flags are needed for everyday development:

```bash
uv run fits-gui
uv run fits-segtune
uv run cellpose
```

The shared default is `[tool.uv].default-groups = ["dev", "cuda126"]` in
`pyproject.toml`. The accelerator groups only affect Windows x64. The `cpu`
and `cuda128` groups remain available for future machines; to temporarily
select one, disable the default accelerator group:

```bash
uv sync --no-group cuda126 --group cpu
uv run --no-group cuda126 --group cpu fits-gui
```

Replace `cpu` with `cuda128` for CUDA 12.8 on compatible hardware. A later
plain `uv sync` or `uv run` restores the shared default. These groups are
mutually exclusive, so do not use `--all-groups`. The former `--extra` GPU
profiles have been replaced by dependency groups.

CUDA 12.6 retains support for the GTX 1080 (Pascal); the CUDA 12.8 build does
not. See [PyTorch's architecture compatibility notice](https://github.com/pytorch/pytorch/issues/157517).
A separate CUDA toolkit installation is not needed.

Check GPU availability from the FITS directory:

```bash
uv run python -c "import torch; from cellpose import core; print(torch.__version__, torch.version.cuda); print('Cellpose GPU:', core.use_gpu())"
```

Restart running Python sessions after changing PyTorch, and enable `use GPU`
in the Cellpose GUI (or pass `--use_gpu` to the Cellpose CLI).

Launch the main settings interface with `uv run fits-gui`, or open the image
tools directly:

```bash
uv run fits-segtune
uv run fits-drawmask
```

In `fits-gui`, select Segmentation and click **Tune segmentation…** to preview
Cellpose with the current settings. **Apply and close** copies the selected
channel and tuning settings back to the main GUI. Closing the tuner without
applying leaves the main settings unchanged. Use Save settings or Run pipeline
in the main GUI to save the changes. Converted `fits_array.tif` images are
required for previewing. When an image is opened, SegTune initializes and caches
the selected Cellpose model in the background without running an automatic
preview. The tuning controls remain editable while it loads, but **Run preview**
stays disabled until the model is ready. Changing the built-in model, custom
model path, or denoising option queues the latest model for initialization.

The main settings interface groups steps into **Convert**, **Preprocess**,
**Process**, and **Analysis** tabs. The step list on the left shows only the
selected phase, and a `✓` in a tab title means that phase contains at least one
enabled step. When a run directory has no `fits_array.tif`, only Convert is
available and **Convert experiment(s)** performs a conversion-only pass. After
successful conversion, the other tabs unlock and the button becomes **Run
pipeline**. **Unlock all phase tabs** in advanced runtime settings allows a
single full run from raw inputs; artifact-dependent viewers remain disabled
until converted arrays really exist.

For enabled steps, the GUI requires conversion channel labels, a channel-
registration reference channel, at least one segmentation channel, and at
least one tracking channel. If one is missing, the GUI keeps the affected step
or phase selected and explains which field must be completed. **Run pipeline**
remains disabled until all required fields belonging to enabled steps have a
value. These checks detect omitted input only; the pipeline continues to handle
invalid channel names and other data-dependent validation.

`fits-drawmask` opens a dedicated mask editor with **Reference** and **ROI**
tabs sharing the same experiment and image controls. `fits-segtune` opens its
own segmentation window; its standalone Apply settings action updates only
the current tuning session and does not write pipeline settings.
Opening an image also loads the first reference and ROI masks beside it, in
filename order. Selecting a mask file opens its sibling image and that specific
mask in the matching tab.
The former `fits-viewer` command has been removed.

To open the collection panel in preview mode without running the pipeline:

```bash
uv run fits-drawmask --tool pipeline
```

Click **Load test experiments…** and choose a folder containing prepared
`fits_array.tif` images. The panel starts in Reference mode. **Go to ROI** /
**Go to ref** switches between Reference and ROI; unsaved changes require confirmation before
being discarded. New experiments join the waiting list without replacing the
current drawing. **Complete ref masks** or **Complete ROI masks** finalizes that
mask type and moves to the other one; completing the second type finishes the
experiment. **Next experiment** finishes the current experiment after any
needed warnings, and remains unavailable until the next queued experiment is
ready. **Complete session** ends collection normally; **Quit pipeline** is a
separate cancellation action. Buttons explain their actions when hovered.

The experiment tree shows all received experiments, highlights the current one,
and lists saved masks underneath each folder. Click a current experiment's mask
to reload it for editing. Masks from other experiments open for viewing only;
**Return to current experiment** restores your ongoing drawing. Newly saved
masks appear in the tree immediately.

**Load test experiments…** is only present in this preview. In the integrated
window, the pipeline supplies prepared experiments automatically; there is no
manual folder loader.

This is a preview with no running pipeline, but **Save writes real mask files**
to the selected experiment folders. The regular `fits-drawmask` command keeps
the standalone browser and visible tabs.

You can also supply `--experiments-dir /path/to/run` and
`--settings /path/to/fits_settings.toml`. Without a settings file, the preview
requests one reference per experiment and no ROI. With settings, it uses the
enabled extraction/distance-profile steps and their drawing options.

To run the connected drawing workflow with slow demonstration steps:

```bash
uv run fits-gui --demo-step-delay 5
```

Choose your run folder and settings in the main GUI, enable **Distance profile**
(or **Quantification → Draw reference masks**), then click **Run pipeline**.
The drawing window opens automatically once the first image is prepared.
Preparation continues for the other experiments, so the queue grows while you
draw. Completing an experiment's masks releases its analysis. Missing
references omit distance profiling for that experiment; no ROI means
whole-image profiling after confirmation.

The delay is five seconds between steps, including between arrivals when images
are already prepared. Ordinary `uv run fits-gui` has no artificial delay.
Interactive runs currently use one preparation worker and one downstream worker;
existing noninteractive batch/conveyor execution remains available. **Quit
pipeline** stops new work and waits for any already-running step to finish.
The drawing requests and early-finish choices are currently run-local; reopening
a run reuses saved masks and asks for finalization again.

The command-line interface is available through `uv run fits --help`. Running
`uv run fits pipeline start` (or `python -m fits.pipeline`) launches the same
Ref/ROI collection window when the configured analyses request interactive
masks. Calling `start_pipeline()` directly stays noninteractive unless a mask
interaction bridge is supplied.

Runtime `log_dir` is the root for logs. FITS creates a `logs/` folder inside
that directory; when `log_dir` is empty, it creates `logs/` inside `run_dir`.

## Repository maintenance

FITS uses Git submodules and a uv workspace. The practical commands for
cloning, updating, editing, adding, and removing submodules are collected in
the [Git and submodule cheatsheet](docs/git_cheatsheet.md).
