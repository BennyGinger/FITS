"""Bounded, requested-plane background previews with public backend reuse."""

import numpy as np
import tifffile

from bg_sub import bg_sub
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub_tuning import BackgroundTuningSession


def test_session_reuses_processor_invalidates_keys_and_bounds_cache(tmp_path):
    """Reuse configuration across settings while caching only requested planes."""
    source = tmp_path / "fits_array.tif"
    image = np.random.default_rng(4).integers(100, 400, (32, 32), dtype=np.uint16)
    tifffile.imwrite(source, image, imagej=True, metadata={"axes": "YX"})
    session = BackgroundTuningSession(source)
    settings = BGSubSettings(size=3)
    channel = session.channel_labels[0]
    try:
        first = session.compute_plane(image, settings, 0, channel, 0)
        processor = session._processor
        assert len(session._previews) == 1
        assert session.cached_preview(settings, 0, channel, 0) is first
        np.testing.assert_array_equal(first, bg_sub(image, size=3, execution="sequential"))
        changed = settings.model_copy(update={"threshold": 0.1})
        assert session.cached_preview(changed, 0, channel, 0) is None
        session.compute_plane(image, changed, 0, channel, 0)
        assert session._processor is processor
        session.compute_plane(image, settings.model_copy(update={"size": 5}), 0, channel, 0)
        assert session._processor is not processor
        for frame in range(12):
            session.compute_plane(image, settings, frame, channel, 0)
        assert len(session._previews) == 8
        assert session.cached_preview(settings, 0, channel, 0) is None
        excluded = settings.model_copy(update={"exclude_channel": [channel]})
        np.testing.assert_array_equal(session.compute_plane(image, excluded, 0, channel, 0), image)
    finally:
        session.close()
    assert not session._previews and session._processor is None
