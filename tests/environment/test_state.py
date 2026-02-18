from pathlib import Path

from fits.environment.state import ExperimentState
from conftest import DummyFitsIO

def test_state_replace_returns_new_instance() -> None:
    s1 = ExperimentState(original_image=Path("a.nd2"))
    s2 = s1.replace(image=Path("out/fits_array.tif"), last_step="convert")

    assert s1 is not s2
    assert s1.image is None
    assert s2.image == Path("out/fits_array.tif")
    assert s2.last_step == "convert"

def test_workdir_none_when_no_image() -> None:
    s = ExperimentState(original_image=Path("a.nd2"))
    assert s.workdir is None

def test_workdir_is_parent_of_image() -> None:
    s = ExperimentState(original_image=Path("a.nd2"), image=Path("/tmp/run/fits_array.tif"))
    assert s.workdir == Path("/tmp/run")


def test_load_custom_metadata_empty_when_no_image() -> None:
    s = ExperimentState(original_image=Path("a.nd2"))
    assert s.load_custom_metadata() == {}

def test_load_custom_metadata_reads_image_metadata(monkeypatch) -> None:
    def fake_from_path(p: Path):
        return DummyFitsIO({"a": 1})
    monkeypatch.setattr("fits.environment.state.FitsIO.from_path", fake_from_path)

    s = ExperimentState(original_image=Path("a.nd2"), image=Path("img.tif"))
    assert s.load_custom_metadata() == {"a": 1}

def test_load_custom_metadata_merges_masks_with_precedence(monkeypatch) -> None:
    def fake_from_path(p: Path):
        if p.name == "img.tif":
            return DummyFitsIO({"k": "img", "shared": 1})
        return DummyFitsIO({"k": "mask", "shared": 2})

    monkeypatch.setattr("fits.environment.state.FitsIO.from_path", fake_from_path)

    s = ExperimentState(
        original_image=Path("a.nd2"),
        image=Path("img.tif"),
        masks=Path("mask.tif"),
    )
    assert s.load_custom_metadata() == {"k": "mask", "shared": 2}