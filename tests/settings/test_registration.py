"""Check registration algorithm names and compatibility with older settings."""

from pathlib import Path
import tomllib

import pytest

from fits.settings.loader import load_settings, run_settings_path, save_run_settings
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings


@pytest.mark.parametrize("settings_type", [RegisterTimeSettings, RegisterChannelSettings])
@pytest.mark.parametrize("value, expected", [("cv2", "cv2"), ("None", None)])
def test_legacy_registration_algorithm(settings_type: type[RegisterTimeSettings] | type[RegisterChannelSettings],
                                       value: str,
                                       expected: str | None,
                                       ) -> None:
    """
    Accept legacy backend values while emitting only the algorithm field.
    """
    settings = settings_type.model_validate({"backend": value})
    assert settings.algorithm == expected
    assert settings.model_dump()["algorithm"] == expected
    assert settings.to_payload_dict()["algorithm"] == expected
    assert "backend" not in settings.model_dump()
    assert "backend" not in settings.to_payload_dict()


@pytest.mark.parametrize("in_place", [False, True])
def test_saved_registration_algorithms_use_current_keys(tmp_path: Path, in_place: bool) -> None:
    """
    Preserve old selections and comments in CLI snapshots, including in-place saves.
    """
    source = run_settings_path(tmp_path) if in_place else tmp_path / "old.toml"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        f'run_dir = "{tmp_path.as_posix()}"\n'
        '[register_time.params]\nbackend = "cv2" # chosen time algorithm\n'
        '[register_channel.params]\nbackend = "scikit" # chosen channel algorithm\n'
        '[track.params]\nbackend = "trackastra"\n',
        encoding="utf-8",
    )
    loaded = load_settings(source)
    assert loaded["register_time"]["params"] == {"algorithm": "cv2"}
    assert loaded["register_channel"]["params"] == {"algorithm": "scikit"}
    saved = save_run_settings(source, tmp_path)
    text = saved.read_text(encoding="utf-8")
    result = tomllib.loads(text)
    assert result["register_time"]["params"] == {"algorithm": "cv2"}
    assert result["register_channel"]["params"] == {"algorithm": "scikit"}
    assert result["track"]["params"] == {"backend": "trackastra"}
    assert "# chosen time algorithm" in text
    assert "# chosen channel algorithm" in text


def test_explicit_algorithm_takes_precedence(tmp_path: Path) -> None:
    """
    Prefer the current key when both old and new names are supplied.
    """
    source = tmp_path / "both.toml"
    source.write_text('[register_time.params]\nalgorithm = "scikit"\nbackend = "cv2"\n',
                      encoding="utf-8",
                      )
    params = load_settings(source)["register_time"]["params"]
    assert params == {"algorithm": "scikit"}
    assert RegisterTimeSettings.model_validate({"algorithm": "scikit", "backend": "cv2"}).algorithm == "scikit"
