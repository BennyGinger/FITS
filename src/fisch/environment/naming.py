"""Current storage names and the historical aliases accepted at read boundaries."""

from __future__ import annotations

from pathlib import Path

RUN_METADATA = '.pipeline'
ACQUISITION_METADATA = '.acquisition'
SETTINGS = 'settings.toml'
PREFIX = 'proc_'
PARQUET_ARTIFACT = b'pipeline_artifact'
PARQUET_MEMBERSHIP = b'pipeline_active_experiments'

CURRENT_IMAGES = ('proc_array.tif', 'proc_array_raw.tif', 'proc_array_reg_channel.tif',
                  'proc_array_reg.tif', 'proc_array_bgsub.tif')
CURRENT_MASKS = ('proc_masks_seg.tif', 'proc_masks_track.tif', 'proc_masks.tif',
                 'proc_track_edited.tif', 'proc_track_edited_filtered.tif')
CURRENT_TABLES = ('proc_quantification.parquet', 'proc_distance_profile.parquet')
REFERENCE = 'proc_ref_{label}.tif'
ROI = 'proc_roi_{label}.tif'
OVERLAY = 'proc_track_overlay'

LEGACY_RUN_METADATA = '.fits'
LEGACY_ACQUISITION_METADATA = '.fits_experiment'
LEGACY_SETTINGS = 'fits_settings.toml'
LEGACY_PREFIX = 'fits_'
LEGACY_PARQUET_ARTIFACT = b'fits_artifact'
LEGACY_PARQUET_MEMBERSHIP = b'fits_active_experiments'
LEGACY_FILES = {name.replace(PREFIX, LEGACY_PREFIX, 1): name
                for name in (*CURRENT_IMAGES, *CURRENT_MASKS, *CURRENT_TABLES)}
LEGACY_FILES.update({'fits_mask.tif': 'proc_masks_seg.tif', 'fits_track.tif': 'proc_masks_track.tif'})
LEGACY_IMAGES = tuple(name for name, target in LEGACY_FILES.items() if target in CURRENT_IMAGES)
LEGACY_MASKS = tuple(name for name, target in LEGACY_FILES.items() if target in CURRENT_MASKS)
INTERNAL_DIRECTORIES = {RUN_METADATA, ACQUISITION_METADATA, LEGACY_RUN_METADATA, LEGACY_ACQUISITION_METADATA}
HISTORY_DIRECTORIES = {'backup', 'legacy', 'settings_history'}


def canonical_name(name: str) -> str:
    """
    Translate only reserved managed names, never arbitrary acquisition filenames.
    """
    if name in LEGACY_FILES:
        return LEGACY_FILES[name]
    if name.startswith('.fits_') and '.centroids-' in name:
        source, suffix = name[1:].split('.centroids-', 1)
        return '.' + canonical_name(source) + '.centroids-' + suffix
    if name in (LEGACY_RUN_METADATA, LEGACY_ACQUISITION_METADATA, LEGACY_SETTINGS):
        return {LEGACY_RUN_METADATA: RUN_METADATA,
                LEGACY_ACQUISITION_METADATA: ACQUISITION_METADATA, LEGACY_SETTINGS: SETTINGS}[name]
    if name.endswith(('_mb.tif', '_cyto.tif')):
        base, suffix = name.rsplit('_', 1)
        return canonical_name(base + '.tif').removesuffix('.tif') + '_' + suffix
    if name.startswith(('fits_ref_', 'fits_roi_', 'fits_track_overlay')):
        return PREFIX + name.removeprefix(LEGACY_PREFIX)
    if name.startswith('fits_settings_') and name.endswith('.toml'):
        return 'settings_' + name.removeprefix('fits_settings_')
    if name.startswith('fits_report_') and name.endswith('.txt'):
        return 'report_' + name.removeprefix('fits_report_')
    if name.startswith(LEGACY_PREFIX) and name.endswith('.log'):
        return 'run_' + name.removeprefix(LEGACY_PREFIX)
    return name


def canonical_path(path: Path) -> Path:
    """
    Rebind reserved path components while keeping user folder and raw file names.
    """
    return Path(*(canonical_name(part) for part in path.parts))


def is_legacy_name(name: str) -> bool:
    """
    Recognize only managed legacy names, including historical metadata folders.
    """
    return canonical_name(name) != name


def metadata_directory(root: Path, *, acquisition: bool = False) -> Path:
    """
    Locate metadata for reading, preferring the current convention when present.
    """
    current = root / (ACQUISITION_METADATA if acquisition else RUN_METADATA)
    legacy = root / (LEGACY_ACQUISITION_METADATA if acquisition else LEGACY_RUN_METADATA)
    return current if current.is_dir() or not legacy.is_dir() else legacy


def branch_patterns() -> tuple[str, ...]:
    """
    Return current and historical REF/ROI patterns for read-only discovery.
    """
    return (REFERENCE.format(label='*'), ROI.format(label='*'), 'fits_ref_*.tif', 'fits_roi_*.tif')


def read_names(current: str) -> tuple[str, ...]:
    """
    Prefer the current filename and then recognize its historical aliases.
    """
    return (current, *(old for old, target in LEGACY_FILES.items() if target == current))


def branch_files(directory: Path, template: str) -> list[Path]:
    """
    Discover current and legacy REF/ROI files without writing into either layout.
    """
    patterns = (template, template.replace(PREFIX, LEGACY_PREFIX, 1))
    return [path for pattern in patterns for path in sorted(directory.glob(pattern.format(label='*'))) if path.is_file()]
