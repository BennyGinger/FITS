from __future__ import annotations
from pathlib import Path
import logging
from typing import TYPE_CHECKING

from fits.environment.context import ExecutionContext
from fits.environment.assembly import assemble_experiment_states
from fits.environment.constant import STEP_CONVERT, RunTimeMode
from fits.workflows.execute import WORKFLOW_ORDER, first_effective_overwrite_step, resolve_effective_workflow_cfg, run_workflow_scheduler_entry, run_workflow
if TYPE_CHECKING:
    from fits.environment.log import LogEmitter
from fits.environment.discovery import collect_supported_files
from fits.environment.log import configure_logging
from fits.environment.runtime import use_ctx, coerce_mode
from fits.settings.loader import load_settings

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path("src/fits/settings/user_settings.toml")


def start_pipeline(settings_path: Path | None = None, gui_emitter: LogEmitter | None = None) -> None:
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
    mode = coerce_mode(rt_settings.get("mode"))
    rt_mode: RunTimeMode = rt_settings.get("execution", "batch")
    
    log_raw = rt_settings.get("log_dir", None)
    log_dir = Path(log_raw).expanduser().resolve() if isinstance(log_raw, str) else log_raw
    console_level = rt_settings.get("console_level", "info")
    file_level = rt_settings.get("file_level", "debug")
    dry_run = rt_settings.get("dry_run", False)
    
    # --- logging setup once ---
    if mode == "gui" and gui_emitter is None:
        raise ValueError("GUI mode requires gui_emitter (create it in the GUI thread and connect it).")
    configure_logging(log_dir=log_dir, mode=mode, console_level=console_level, file_level=file_level, gui_emitter=gui_emitter)

    # --- context setup once ---
    ctx = ExecutionContext(user_name=user_name, dry_run=dry_run, mode=mode, run_dir=run_dir)
    
    # --- main execution block with context ---
    with use_ctx(ctx):
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

        effective_cfg = resolve_effective_workflow_cfg(user_cfg, WORKFLOW_ORDER)
        logger.info("Using effective workflow config with overwrite cascade applied")
        for step_name in WORKFLOW_ORDER:
            step_cfg = effective_cfg.get(step_name) or {}
            if step_cfg.get("enabled", False):
                logger.debug("Effective step config: %s overwrite=%s", step_name, (step_cfg.get("params") or {}).get("overwrite", False),)

        first_overwrite = first_effective_overwrite_step(effective_cfg, WORKFLOW_ORDER)
        ignore_saved_states = first_overwrite == STEP_CONVERT
        if ignore_saved_states:
            logger.info("Effective overwrite starts at '%s'; seeding raw states for processing", STEP_CONVERT)
        
        # --- build ExperimentState list from saved states + newly discovered raw files ---
        states = assemble_experiment_states(run_dir, supported_files, ignore_saved_states=ignore_saved_states)
        
        # --- start the workflow ---
        logger.debug(f"Loaded user configuration {user_cfg}")
        
        match rt_mode:
            case "batch":
                logger.info("Starting batch execution of workflow")
                final_states = run_workflow(effective_cfg, states)
            case "conveyor":
                logger.info("Starting conveyor execution of workflow")
                final_states = run_workflow_scheduler_entry(effective_cfg, states)
        
        logger.info("Pipeline finished with %d final experiment states", len(final_states))
        for st in final_states:
            logger.debug("Final state: exp_id=%s image=%s masks=%s last_step=%s", st.experiment_id,
                                                                                    st.image_rel,
                                                                                    st.masks_rel,
                                                                                    st.last_step,
                                                                                )


if __name__ == "__main__":
    from time import time
    start_time = time()
    
    start_pipeline()
    end_time = time()
    elapsed = end_time - start_time
    print(f"Total pipeline execution time: {elapsed:.2f} seconds")
    
    
    