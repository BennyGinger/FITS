from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from fits.environment.constant import Mode
from fits.environment.context import ExecutionContext
if TYPE_CHECKING:
    from fits.environment.log import LogEmitter
from fits.environment.log import configure_logging
from fits.environment.runtime import detect_mode, use_ctx


def start_pipeline(user_cfg: Mapping[str, Any], gui_emitter: LogEmitter | None = None) -> None:
    
    # --- required globals ---
    run_dir = user_cfg.get("run_dir", None)
    user_name = user_cfg.get("user_name", None)
    if run_dir is None or user_name is None:
        raise ValueError("Both 'run_dir' and 'user_name' must be provided in the configuration.")
    run_dir = Path(run_dir)
    
    # --- runtime config ---
    rt_settings = user_cfg.get("runtime", {})
    mode: Mode = rt_settings.get("mode") or detect_mode()
    
    log_dir = rt_settings.get("log_dir", None)
    log_dir = Path(log_dir) if isinstance(log_dir, str) else log_dir
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
    
    # --- Main execution block with context ---
    with use_ctx(ctx):
        # --- discover images ---
        
        # Build ExperimentState for each file
        
        # Start the workflow
        
    
        pass