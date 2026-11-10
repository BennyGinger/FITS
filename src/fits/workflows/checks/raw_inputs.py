"""Read-only raw acquisition validation shared by the pipeline and GUI."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from scope_io import ScopeIO
from scope_io.metadata.resolve import channel_label_warning
from fits.environment.paths import EXPERIMENT_DIR_NAME
from fits.workflows.checks.models import RawInputReport
from fits.workflows.experiments import collect_supported_files


def _display_path(path: Path, root: Path) -> str:
    """
    Display a run-relative path when the input belongs to the run.
    """
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def _plan_acquisition_directories(files: Sequence[Path], root: Path) -> tuple[dict[Path, Path], list[str]]:
    """
    Plan unique grouping folders without renaming or moving original files.
    """
    ungrouped = [path for path in files if not (path.parent / EXPERIMENT_DIR_NAME).is_dir()]
    stems = Counter((path.parent, path.stem) for path in ungrouped)
    directories: dict[Path, Path] = {}
    destinations: dict[Path, list[Path]] = {}
    problems: list[str] = []
    for path in ungrouped:
        name = path.stem
        if stems[path.parent, path.stem] > 1:
            name += f"_{path.suffix[1:].lower()}"
        target = path.parent / name
        directories[path] = target
        destinations.setdefault(target, []).append(path)
    grouped_stems: dict[tuple[Path, str], list[Path]] = {}
    for path in files:
        if path not in directories:
            grouped_stems.setdefault((path.parent, path.stem), []).append(path)
    for (parent, stem), sources in grouped_stems.items():
        if len(sources) > 1:
            inputs = "\n".join(f"  {_display_path(path, root)}" for path in sources)
            problems.append(f"Duplicate stem {stem!r} inside existing acquisition folder: {_display_path(parent, root)}.\n"
                            f"{inputs}\nMove newly added inputs into a separate run subfolder before conversion; "
                            "existing acquisition paths must remain intact.")
    for target, sources in destinations.items():
        if target.exists() or len(sources) > 1:
            inputs = "\n".join(f"  {_display_path(path, root)}" for path in sources)
            problems.append(f"Cannot create acquisition folder: {_display_path(target, root)}. "
                            "The destination already exists or is shared by multiple inputs.\n"
                            f"{inputs}\nRename the affected input files or resolve the existing folder before conversion.")
    return directories, problems


def channel_label_warnings(counts: dict[Path, int], labels: Sequence[str] | None) -> tuple[str, ...]:
    """
    Warn about label counts without blocking conversion or duplicating mixed-input errors.
    """
    expected = set(counts.values())
    if not labels or len(expected) != 1:
        return ()
    count = next(iter(expected))
    warning = channel_label_warning(count, len(labels), default_labels=[f"C{index + 1}" for index in range(count)])
    return (warning,) if warning else ()


def inspect_raw_inputs(root: Path,
                       files: Sequence[Path] | None = None,
                       *,
                       channel_labels: Sequence[str] | None = None,
                       ) -> RawInputReport:
    """
    Check channel/frame counts and acquisition destinations without reading image pixels or changing files.
    """
    root = root.expanduser().resolve()
    sources = sorted({path.resolve() for path in (collect_supported_files(root) if files is None else files)})
    counts: dict[Path, int] = {}
    frames: dict[Path, tuple[int, ...]] = {}
    colors: dict[Path, list[str | None] | None] = {}
    problems: list[str] = []
    for path in sources:
        try:
            reader = ScopeIO.from_path(path).reader
            frame_counts = tuple(series.shape[series.axes.index("T")] if "T" in series.axes else 1
                                 for series in reader.split_series())
            counts[path] = reader.channel_count
            colors[path] = reader.channel_colors
            frames[path] = frame_counts
        except Exception as error:
            problems.append(f"Cannot read raw input metadata: {_display_path(path, root)}.\n"
                            f"{error}\nCheck that this is a readable supported ND2/TIFF acquisition.")
    if len(set(counts.values())) > 1:
        values = ", ".join(str(count) for count in sorted(set(counts.values())))
        inputs = "\n".join(f"  {_display_path(path, root)}: {count} {'channel' if count == 1 else 'channels'}"
                           for path, count in counts.items())
        problems.append(f"Cannot convert files with different numbers of channels ({values}).\n{inputs}\n"
                        "Place acquisitions with different channel counts in separate run directories.")
    directories, destination_problems = _plan_acquisition_directories(sources, root)
    return RawInputReport(counts, directories, tuple(problems + destination_problems),
                          channel_label_warnings(counts, channel_labels),
                          frames,
                          colors,
                          )
