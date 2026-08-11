from __future__ import annotations

import os

os.environ["TQDM_DISABLE"] = "1" # Silence tqdm progress bars of trackastra pkg

from pathlib import Path
import logging

from fits.environment.constant import RunTimeMode, WORKFLOW_ORDER
from fits.settings.resolution import apply_overwrite_cascade
from fits.workflows.execute import run_workflow_scheduler_entry, run_workflow
from fits.environment.discovery import collect_supported_files, assemble_experiment_states
from fits.environment.log import configure_logging
from fits.settings.loader import load_settings


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).parent / "settings" / "user_settings.toml"


def start_pipeline(settings_path: Path | None = None) -> None:
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
    rt_mode: RunTimeMode = rt_settings.get("execution", "batch")
    
    log_raw = rt_settings.get("log_dir", None)
    log_dir = Path(log_raw).expanduser().resolve() if isinstance(log_raw, str) else log_raw
    console_level = rt_settings.get("console_level", "info")
    file_level = rt_settings.get("file_level", "debug")
    
    # --- logging setup once ---
    configure_logging(log_dir=log_dir,console_level=console_level, file_level=file_level)

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
    
    # --- build ExperimentState list from saved states + newly discovered raw files ---
    states = assemble_experiment_states(run_dir, supported_files, effective_cfg, user_name)
    
    # --- start the workflow ---
    match rt_mode:
        case "batch":
            logger.info("Starting batch execution of workflow")
            final_states = run_workflow(effective_cfg, states)
        case "conveyor":
            logger.info("Starting conveyor execution of workflow")
            final_states = run_workflow_scheduler_entry(effective_cfg, states)
    
    logger.info("Pipeline finished with %d final experiment states", len(final_states))
    for st in final_states:
        logger.debug("Final state: exp_id=%s last_step=%s", st.experiment_id, st.last_step,)


if __name__ == "__main__":
    from time import time
    start_time = time()
    
    start_pipeline()
    end_time = time()
    elapsed = end_time - start_time
    print(f"Total pipeline execution time: {elapsed:.2f} seconds")
    
    
    