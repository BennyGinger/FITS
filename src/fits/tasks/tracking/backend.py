from tracklink.api import TrackModel

from fits.settings.models import TrackSettings


def create_tracker(settings: TrackSettings) -> TrackModel:
    """Create and configure the selected tracking backend."""
    tracker = TrackModel(backend=settings.backend)
    backend_settings = getattr(settings, settings.backend, {})
    tracker.configure(backend_settings)
    return tracker
