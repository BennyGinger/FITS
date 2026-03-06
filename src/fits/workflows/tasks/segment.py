from collections.abc import Iterator
import logging

from fits_io.client import FitsIO
from progress_bar.decorator import pbar

from fits.environment.constant import ExecMode, FITS_MASK_NAME, FitsName
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentSettings
from fits.workflows.executors import execute
from fits.workflows.payload import build_fits_payload, hash_payload
from fits.workflows.provenance import StepProfile
from fits.workflows.tasks.segment_utils.model_cache import segment_model_cache
from fits.workflows.tasks.metadata import OutputStateMeta
from fits.workflows.tasks.segment_utils.array import get_array


logger = logging.getLogger(__name__)


def segment_one(settings: SegmentSettings, exp_state: ExperimentState, step_profile: StepProfile, output_name: FitsName) -> ExperimentState:
    """
    Process a single experiment through the segment step.

    Args:
        settings: Segment step settings
        exp_state: Single experiment state to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Returns:
        Single output experiment state.
    """
    # TODO: for ProcessPool execution, pass ExecutionContext explicitly (ContextVar doesn't propagate).
    ctx = get_ctx()

    payload_full = build_fits_payload(
        step_profile,
        **settings.model_dump(),
        user_name=ctx.user_name,
        output_name=output_name,
    )
    settings_hash = hash_payload(payload_full)
    chan_seg = list(settings.channel_to_segment)
    chan_nuc = list(settings.nuclear_channel)
    requested_channels = list(dict.fromkeys(chan_seg + chan_nuc))

    logger.debug("Will be executed with parameters: %s", payload_full)

    if not exp_state.needs_run(
        step_profile.step_name,
        settings_hash,
        requested_channels,
        settings.overwrite,
        FITS_MASK_NAME,
    ):
        logger.debug("Skipping %s for %s as it is up to date.", step_profile.step_name, exp_state.original_image)
        return exp_state

    if exp_state.image is None:
        raise ValueError(
            f"ExperimentState for {exp_state.original_image} has no image set; cannot run {step_profile.step_name}."
        )

    reader = FitsIO.from_path(exp_state.image)
    input_array, input_axis_order = get_array(reader, requested_channels)

    cp_payload = settings.model_dump()
    cp_wrapper = segment_model_cache.get_wrapper(cp_payload)
    masks_array = cp_wrapper.run(input_array, input_axis_order)

    # Save payload should not include segmentation settings unless explicitly desired in FITS metadata.
    payload_save = build_fits_payload(
        step_profile,
        user_name=ctx.user_name,
        output_name=output_name,
    )
    out_axis_order = cp_wrapper.output_axis_order
    if out_axis_order is None:
        raise ValueError("Output axis order from CellposeWrapper is None. Cannot save output without axis order information.")

    save_path = reader.save_array(
        masks_array,
        axis_order=out_axis_order,
        channel_labels=chan_seg,
        **payload_save,
        custom_metadata=cp_wrapper.segmentation_meta,
    )
    logger.info("%s completed for %s", step_profile.step_name, exp_state.workdir)

    out_meta = OutputStateMeta(
        step=step_profile.step_name,
        axes=out_axis_order,
        channel_labels=chan_seg,
        hashed_settings=settings_hash,
        with_masks=save_path,
        mark_done=True,
    )

    new_st = exp_state.with_update(out_meta)
    logger.debug("Produced new ExperimentState: %s", new_st)
    new_st.to_json()
    return new_st


@pbar(desc="Segment")
def run_segment(settings: SegmentSettings, exp_state: list[ExperimentState], step_profile: StepProfile, output_name: FitsName) -> Iterator[list[ExperimentState]]:
    """
    Batch runner for segment step. Maps segment_one across experiments.

    Args:
        settings: Segment step settings
        exp_state: List of experiment states to process
        step_profile: Step metadata
        output_name: Output FITS name scheme

    Yields:
        List containing a single output experiment state for each completed input experiment.
    """
    ctx = get_ctx()
    
    payload = build_fits_payload(
        step_profile,
        **settings.model_dump(),
        user_name=get_ctx().user_name,
        output_name=output_name,
    )
    logger.debug("Payload for %s: %s", step_profile.step_name, payload)

    exec_mode: ExecMode = settings.execution
    workers: int | None = settings.workers
    ordered: bool = settings.ordered_execution
    logger.debug(
        "Executing %s with mode: %s and workers: %s in ordered mode: %s",
        step_profile.step_name,
        exec_mode,
        workers,
        ordered,
    )

    logger.info("Starting %s with settings: %s", step_profile.step_name, payload)

    def worker(st: ExperimentState) -> list[ExperimentState]:
        with use_ctx(ctx):  # Ensure the execution context is available in worker
            return [segment_one(settings, st, step_profile, output_name)]

    return execute(exp_state, worker, mode=exec_mode, workers=workers, ordered=ordered)
        

    



