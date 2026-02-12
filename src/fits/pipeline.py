from __future__ import annotations
from pathlib import Path
import logging
from typing import TYPE_CHECKING

from fits.environment.context import ExecutionContext
from fits.environment.state import ExperimentState
from fits.workflows.execute import run_workflow
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
    ctx = ExecutionContext(user_name=user_name,
                           dry_run=dry_run,
                           mode=mode)
    
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
                logger.warning(
                    f"optimize path {optimize_path} was provided but was not found among discovered supported files under {run_dir}; "
                    "continuing with full pipeline.")
        
        # --- build ExperimentState for each file ---
        states = [ExperimentState(original_image=f) for f in supported_files]
        
        # --- start the workflow ---
        run_workflow(user_cfg, states)


if __name__ == "__main__":
    from fits_io import FitsIO
    
    # start_pipeline()
    
    out_path = Path('/media/ben/Analysis/Python/Docker_mount/Test_images/nd2/Run2_test/stimulated/c2z25t23v1_nd2_s1/fits_array.tif')
    reader = FitsIO.from_path(out_path)
    print("_________________________")
    print(reader.fits_metadata)
    print(reader.channel_labels)
    