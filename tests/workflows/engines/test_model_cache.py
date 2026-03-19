from __future__ import annotations

from fits.workflows.engines.model_cache import SegmentModelCache


class FakeWrapper:
    calls: list[dict] = []

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.setup_calls = 0

    def setup(self) -> None:
        self.setup_calls += 1

    @classmethod
    def from_dict(cls, settings: dict):
        cls.calls.append(dict(settings))
        return cls(settings)


def test_model_cache_reuses_wrapper_for_same_model_settings(monkeypatch) -> None:
    FakeWrapper.calls = []
    monkeypatch.setattr('fits.workflows.engines.model_cache.CellposeWrapper', FakeWrapper)
    cache = SegmentModelCache()

    first = cache.get_wrapper({'model': 'cyto', 'user_settings': {'diameter': 20}, 'extra': 'ignored'})
    second = cache.get_wrapper({'model': 'cyto', 'user_settings': {'diameter': 20}, 'different': 'also ignored'})

    assert first is second
    assert first.setup_calls == 1
    assert FakeWrapper.calls == [{'model': 'cyto', 'user_settings': {'diameter': 20}, 'extra': 'ignored'}]


def test_model_cache_clear_cache_forces_new_wrapper(monkeypatch) -> None:
    FakeWrapper.calls = []
    monkeypatch.setattr('fits.workflows.engines.model_cache.CellposeWrapper', FakeWrapper)
    cache = SegmentModelCache()

    first = cache.get_wrapper({'model': 'cyto', 'user_settings': 'bad-shape'})
    cache.clear_cache()
    second = cache.get_wrapper({'model': 'cyto', 'user_settings': 'bad-shape'})

    assert first is not second
    assert FakeWrapper.calls == [
        {'model': 'cyto', 'user_settings': 'bad-shape'},
        {'model': 'cyto', 'user_settings': 'bad-shape'},
    ]
    assert cache._extract_model_settings({'model': 'cyto', 'user_settings': 'bad-shape'}) == {
        'model': 'cyto',
        'user_settings': {},
    }