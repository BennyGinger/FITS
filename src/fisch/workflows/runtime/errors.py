"""Exceptions raised while executing workflows and individual tasks."""


class StepExecutionError(RuntimeError):
    """A workflow step failed for one experiment."""


class PipelineCancelled(Exception):
    """User-requested cancellation, distinct from a processing failure."""


class AllExperimentsFailed(RuntimeError):
    """Every discovered experiment failed before producing a final state."""
