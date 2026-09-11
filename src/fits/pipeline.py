from __future__ import annotations

import os


os.environ["TQDM_DISABLE"] = "1" # Silence tqdm progress bars of trackastra pkg
from pathlib import Path
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fits.environment.progress import RunProgress

from fits.environment.constant import RunTimeMode, WORKFLOW_ORDER
from fits.settings.resolution import apply_overwrite_cascade
from fits.workflows.execute import run_workflow_scheduler_entry, run_workflow
from fits.environment.discovery import collect_supported_files, assemble_experiment_states
from fits.environment.log import configure_logging
from fits.environment.report import format_run_report
from fits.settings.loader import load_settings
from fits.tasks import aggregate_distance_profiles, aggregate_quantification


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).parent / "settings" / "user_settings.toml"


def start_pipeline(
    settings_path: Path | None = None,
    console_handler: logging.Handler | None = None,
    mask_interaction=None,
    demo_step_delay: float = 0.0,
    run_progress: RunProgress | None = None,
    convert_only: bool = False,
) -> None:
    # --- load settings ---
    cfg_path = (settings_path or SETTINGS_PATH).expanduser().resolve()
    user_cfg = load_settings(cfg_path)
    
    # --- required globals ---
    run_raw = user_cfg.get("run_dir", None)
    user_name = user_cfg.get("user_name", None)
    if run_raw is None or user_name is None:
        raise ValueError("Both 'run_dir' and 'user_name' must be provided in the configuration.")
    run_dir = Path(run_raw).expanduser().resolve()
    
    # --- runtime config ---
    rt_settings = user_cfg.get("runtime", {})
    rt_mode: RunTimeMode = rt_settings.get("execution", "conveyor")
    
    log_raw = rt_settings.get("log_dir")
    if isinstance(log_raw, str):
        log_raw = log_raw.strip()
    log_root = Path(log_raw).expanduser().resolve() if log_raw else run_dir
    log_dir = log_root / "logs"
    console_level = rt_settings.get("console_level", "info")
    file_level = rt_settings.get("file_level", "debug")
    
    # --- logging setup once ---
    log_path = configure_logging(
        log_dir=log_dir,
        console_level=console_level,
        file_level=file_level,
        console_handler=console_handler,
    )

    # --- discover images ---
    supported_files = collect_supported_files(run_dir)
    
    # --- optimization ---
    optimize_raw = user_cfg.get("optimize", None)
    optimize_path = None
    if isinstance(optimize_raw, str) and optimize_raw.strip():
        optimize_path = Path(optimize_raw).expanduser().resolve()
    
    if optimize_path is not None:
        matches = [p for p in supported_files if p.resolve() == optimize_path]
        if matches: # optimize path is in supported files
            logger.info(f"Optimization mode: only processing {optimize_path}")
            supported_files = matches
        else:
            logger.warning(f"optimize path {optimize_path} was provided but was not found among discovered supported files under {run_dir}; "
                "continuing with full pipeline.")

    # --- apply overwrite cascade to user config ---
    effective_cfg = apply_overwrite_cascade(user_cfg, WORKFLOW_ORDER)
    if convert_only:
        for step_name in WORKFLOW_ORDER:
            if step_name in effective_cfg:
                effective_cfg[step_name]["enabled"] = step_name == "convert"
    
    # --- build ExperimentState list from saved states + newly discovered raw files ---
    states = assemble_experiment_states(run_dir, supported_files, effective_cfg, user_name)

    def save_progress_report() -> None:
        if run_progress is None or log_path is None or not run_progress.snapshot():
            return
        timestamp = log_path.stem.removeprefix("fits_")
        report_path = log_path.with_name(f"fits_report_{timestamp}.txt")
        report_path.write_text(
            format_run_report(run_progress, run_dir, include_header=True) + "\n",
            encoding="utf-8")
        logger.info("Full pipeline report saved to %s", report_path)
    
    # --- start the workflow ---
    from fits.workflows.interactive import interactive_masks_requested, run_interactive_workflow
    try:
        if convert_only:
            from fits.workflows.interactive import run_conversion_only
            logger.info("Starting conversion-only execution.")
            final_states = run_conversion_only(
                effective_cfg,
                states,
                step_delay_seconds=demo_step_delay,
                progress=run_progress,
            )
        elif mask_interaction is not None and interactive_masks_requested(effective_cfg):
            logger.info("Starting interactive conveyor: preparation continues while masks are drawn.")
            final_states = run_interactive_workflow(
                effective_cfg, states, mask_interaction,
                step_delay_seconds=demo_step_delay, progress=run_progress)
        else:
            match rt_mode:
                case "batch":
                    logger.info("Starting batch execution of workflow")
                    final_states = run_workflow(effective_cfg, states)
                case "conveyor":
                    logger.info("Starting conveyor execution of workflow")
                    final_states = run_workflow_scheduler_entry(effective_cfg, states)
    except BaseException:
        save_progress_report()
        raise
    
    # --- log final states ---
    for st in final_states:
        logger.debug("Final state: exp_id=%s last_step=%s", st.experiment_id, st.last_step,)

    # --- aggregate quantification artifacts into a master Parquet file, only if needed ---
    try:
        aggregate_quantification(effective_cfg, final_states, run_dir)
        aggregate_distance_profiles(effective_cfg, final_states, run_dir)
    finally:
        save_progress_report()
    
    logger.info("Pipeline finished with %d final experiment states", len(final_states))

if __name__ == "__main__":
    from time import time
    from fits.cli.interactive import run_pipeline_cli
    start_time = time()

    run_pipeline_cli()
    end_time = time()
    elapsed = end_time - start_time
    print(f"Total pipeline execution time: {elapsed:.2f} seconds")
