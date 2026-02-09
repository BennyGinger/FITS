from __future__ import annotations
from pathlib import Path

from fits.environment.discovery import collect_supported_files, find_fits_outputs
from fits.environment.constant import FITS_ARRAY_NAME, FITS_MASK_NAME


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")  # content irrelevant
    return p


def test_collect_supported_files_recursive_and_filters(tmp_path: Path) -> None:
    # supported
    a = touch(tmp_path / "a.tif")
    b = touch(tmp_path / "sub" / "b.nd2")
    c = touch(tmp_path / "deep" / "more" / "c.tiff")

    # excluded prefix
    touch(tmp_path / "fits_skip.tif")
    touch(tmp_path / "sub" / "fits_skip2.nd2")

    # unsupported files
    touch(tmp_path / "notes.csv")
    touch(tmp_path / "sub" / "report.pdf")

    out = collect_supported_files(tmp_path)

    assert set(out) == {a, b, c}
    assert out == sorted(out)


def test_collect_supported_files_extension_is_case_insensitive(tmp_path: Path) -> None:
    a = touch(tmp_path / "A.TIF")
    b = touch(tmp_path / "B.TiF")
    out = collect_supported_files(tmp_path)
    assert set(out) == {a, b}


def test_find_fits_outputs_finds_expected_names_recursively(tmp_path: Path) -> None:
    a = touch(tmp_path / FITS_ARRAY_NAME)
    b = touch(tmp_path / "sub" / FITS_MASK_NAME)
    touch(tmp_path / "sub" / "other.tif")

    out = find_fits_outputs(tmp_path)

    assert set(out) == {a, b}
    assert out == sorted(out)


def test_find_fits_outputs_does_not_match_similar_names(tmp_path: Path) -> None:
    touch(tmp_path / (FITS_ARRAY_NAME.replace(".tif", "_copy.tif")))
    touch(tmp_path / f"copy_{FITS_MASK_NAME}")
    out = find_fits_outputs(tmp_path)
    assert out == []
