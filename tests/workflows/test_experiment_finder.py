from pathlib import Path

import pytest

# CHANGE THIS import to match your project layout
import fits.environment.experiment_finder as ef

from fits.environment.models import ExperimentModel


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")
    return p


def test__rglob_excludes_prefixes(tmp_path: Path) -> None:
    _touch(tmp_path / "a.tif")
    _touch(tmp_path / "fits_generated.tif")
    _touch(tmp_path / "sub" / "b.tif")
    _touch(tmp_path / "sub" / "fits_b.tif")

    out = ef._rglob(tmp_path, "*.tif")
    names = {p.name for p in out}

    assert "a.tif" in names
    assert "b.tif" in names
    assert "fits_generated.tif" not in names
    assert "fits_b.tif" not in names


def test_find_supported_files_collects_and_sorts(tmp_path: Path) -> None:
    # supported
    a = _touch(tmp_path / "b.tif")
    b = _touch(tmp_path / "a.nd2")
    c = _touch(tmp_path / "sub" / "c.tiff")
    # excluded prefix
    _touch(tmp_path / "fits_skip.tif")
    # unsupported extension
    _touch(tmp_path / "nope.png")

    out = ef.collect_supported_files(tmp_path)

    # should include only supported, excluding prefix
    assert set(out) == {a, b, c}
    # sorted
    assert out == sorted(out)


@pytest.mark.parametrize(
    "spec,n_items,expected",
    [
        ("", 10, set()),
        ("  ", 10, set()),
        ("1", 5, {0}),
        ("5", 5, {4}),
        ("1-3", 10, {0, 1, 2}),
        ("3-1", 10, {0, 1, 2}),  # reversed range is accepted by your implementation
        ("1-3,6-7,10", 10, {0, 1, 2, 5, 6, 9}),
        (" 1 - 2 , 4 ", 10, {0, 1, 3}),
    ],
)
def test__parse_remove_spec_valid(spec: str, n_items: int, expected: set[int]) -> None:
    assert ef._parse_remove_spec(spec, n_items=n_items) == expected


@pytest.mark.parametrize(
    "spec,n_items",
    [
        ("0", 10),          # must be >= 1
        ("-1", 10),
        ("1-", 10),         # invalid range token
        ("-3", 10),         # invalid range token
        ("11", 10),         # out of range
        ("1-11", 10),       # out of range
        ("a", 10),          # not int
        ("1,a", 10),
    ],
)
def test__parse_remove_spec_invalid(spec: str, n_items: int) -> None:
    with pytest.raises(ValueError):
        ef._parse_remove_spec(spec, n_items=n_items)


def test_prompt_experiment_exclusion_enter_selects_all(tmp_path: Path) -> None:
    exp_list = [
        ExperimentModel(img_path=tmp_path / "x.tif", serie_dir=Path("s1")),
        ExperimentModel(img_path=tmp_path / "y.tif", serie_dir=Path("s2")),
    ]

    def fake_input(_prompt: str) -> str:
        return ""  # user presses enter

    printed: list[str] = []

    def fake_print(msg: str) -> None:
        printed.append(msg)

    out = ef.prompt_experiment_exclusion(exp_list, input_fn=fake_input, print_fn=fake_print)
    assert out == exp_list
    # prints numbered lines
    assert any("1" in line and "s1" in line for line in printed)
    assert any("2" in line and "s2" in line for line in printed)


def test_prompt_experiment_exclusion_quit_raises(tmp_path: Path) -> None:
    exp_list = [ExperimentModel(img_path=tmp_path / "x.tif", serie_dir=Path("s1"))]

    def fake_input(_prompt: str) -> str:
        return "q"

    with pytest.raises(ef.UserQuit):
        ef.prompt_experiment_exclusion(exp_list, input_fn=fake_input)


def test_prompt_experiment_exclusion_invalid_then_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exp_list = [
        ExperimentModel(img_path=tmp_path / "x.tif", serie_dir=Path("s1")),
        ExperimentModel(img_path=tmp_path / "y.tif", serie_dir=Path("s2")),
        ExperimentModel(img_path=tmp_path / "z.tif", serie_dir=Path("s3")),
    ]

    answers = iter(["0", "2"])  # first invalid, then remove item 2

    def fake_input(_prompt: str) -> str:
        return next(answers)

    out = ef.prompt_experiment_exclusion(exp_list, input_fn=fake_input, print_fn=lambda _m: None)
    # removed "2" => keep indices 0 and 2
    assert [e.serie_dir.name for e in out] == ["s1", "s3"]


def test_collect_experiments_builds_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # create supported files on disk so find_supported_files sees them
    f1 = _touch(tmp_path / "a.tif")
    f2 = _touch(tmp_path / "sub" / "b.nd2")

    class DummyReader:
        def __init__(self, path: Path) -> None:
            self.path = path

    def fake_get_reader(p: Path) -> DummyReader:
        return DummyReader(p)

    def fake_generate_save_dirs(_reader: DummyReader) -> list[Path]:
        return [Path("s1"), Path("s2")]

    # IMPORTANT: patch on the module under test (ef), not on fits_io
    monkeypatch.setattr(ef, "get_reader", fake_get_reader)
    monkeypatch.setattr(ef, "generate_save_dirs", fake_generate_save_dirs)

    out = ef.collect_experiments(tmp_path)

    # 2 files * 2 series dirs each = 4 models
    assert len(out) == 4
    assert {m.img_path for m in out} == {f1, f2}
    assert {m.serie_dir for m in out} == {Path("s1"), Path("s2")}


def test_collect_experiments_skips_bad_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    good = _touch(tmp_path / "good.tif")
    bad = _touch(tmp_path / "bad.tif")

    def fake_get_reader(p: Path):
        if p.name == "bad.tif":
            raise RuntimeError("boom")
        return object()

    def fake_generate_save_dirs(_reader) -> list[Path]:
        return [Path("s1")]

    monkeypatch.setattr(ef, "get_reader", fake_get_reader)
    monkeypatch.setattr(ef, "generate_save_dirs", fake_generate_save_dirs)

    with caplog.at_level("ERROR"):
        out = ef.collect_experiments(tmp_path)

    # only good file yielded one model
    assert len(out) == 1
    assert out[0].img_path == good
    assert any("Error reading" in rec.message for rec in caplog.records)


def test_select_experiments_wires_collect_and_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models = [
        ExperimentModel(img_path=tmp_path / "x.tif", serie_dir=Path("s1")),
        ExperimentModel(img_path=tmp_path / "y.tif", serie_dir=Path("s2")),
    ]

    monkeypatch.setattr(ef, "collect_experiments", lambda _d: models)
    monkeypatch.setattr(ef, "prompt_experiment_exclusion", lambda xs: xs[:1])

    out = ef.select_experiments(tmp_path)
    assert out == models[:1]
