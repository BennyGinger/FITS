from __future__ import annotations


import os
os.environ["TQDM_DISABLE"] = "1" # Silence tqdm progress bars of trackastra pkg
import logging
from collections.abc import Callable
from fits.workflows.checks.models import PreflightReport, PreflightRequired
from fits.workflows.checks.artifacts import inspect_run
from fits.workflows.checks.pipeline import require_pipeline_space
from fits.workflows.checks.raw_inputs import inspect_raw_inputs
from fits.workflows.file_management.snapshots import rebuild_backup_size, replacement_states, retain_rebuild_backups
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.runtime.interactive.interaction import PipelineInteraction
from fits.workflows.file_management.rebuild import ProcessingPlan, execution_config, upgrade_execution_config
from pathlib import Path
from copy import deepcopy
from fits.workflows.runtime.progress import RunProgress, format_run_report
from fits.environment.constant import RunTimeMode, WORKFLOW_ORDER, ARTI_IMG_RAW, ARTI_IMG
from fits.settings.resolution import apply_overwrite_cascade
from fits.workflows.runtime.batch import run_batch_workflow
from fits.workflows.runtime.scheduler import run_workflow_scheduler
from fits.workflows.experiments import assemble_experiment_states, collect_supported_files, discover_saved_states
from fits.environment.log import configure_logging
from fits.environment.paths import ensure_fits_directory, logs_dir, reports_dir
from fits.settings.loader import load_settings, save_run_settings
from fits.tasks import aggregate_distance_profiles, aggregate_quantification
from fits.workflows.experiments.roots import resolve_run_root
from fits.workflows.checks.compatibility import require_current_run
from dataclasses import replace
from fits.workflows.definitions.inputs import IMAGE_OUTPUTS
from fits.workflows.runtime.interactive import interactive_inputs_requested, run_interactive_workflow, run_conversion_only
from fits.workflows.artifacts.branch_masks import refresh_branches
from fits.workflows.file_management.snapshots import preserve_replaced_results


logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(__file__).parent / "settings" / "user_settings.toml"


def start_pipeline(settings_path: Path | None = None,
                   console_handler: logging.Handler | None = None,
                   interaction: PipelineInteraction | None = None,
                   demo_step_delay: float = 0.0,
                   run_progress: RunProgress | None = None,
                   convert_only: bool = False,
                   force_conversion: bool = False,
                   artifact_decision: Callable[[PreflightReport], str] | None = None,
                   terminal_progress: bool = True,
                   upgrading: bool = False,
                   maintenance: ProcessingPlan | None = None,
                   ) -> None:
    # --- load settings ---
    """
    Run configured steps using saved state and explicitly reviewed artifact decisions.
    """
    cfg_path = (settings_path or SETTINGS_PATH).expanduser().resolve()
    user_cfg = load_settings(cfg_path)

    # --- required globals ---
    run_raw = user_cfg.get("run_dir", None)
    user_name = user_cfg.get("user_name", None)
    if run_raw is None or user_name is None:
        raise ValueError("Both 'run_dir' and 'user_name' must be provided in the configuration.")
    if cfg_path.parent.name == '.fits' and cfg_path.name == 'fits_settings.toml':
        run_raw = cfg_path.parent.parent
    run_dir = resolve_run_root(Path(run_raw))
    user_cfg['run_dir'] = str(run_dir)
    if not upgrading:
        require_current_run(run_dir)

    # --- runtime config ---
    rt_settings = user_cfg.get("runtime", {})
    rt_mode: RunTimeMode = rt_settings.get("execution", "conveyor")

    log_raw = rt_settings.get("log_dir")
    if isinstance(log_raw, str):
        log_raw = log_raw.strip()
    log_root = Path(log_raw).expanduser().resolve() if log_raw else run_dir
    log_dir = logs_dir(log_root)
    report_dir = reports_dir(log_root)
    console_level = rt_settings.get("console_level", "info")
    file_level = rt_settings.get("file_level", "debug")

    # --- discover images ---
    supported_files = collect_supported_files(run_dir)
    all_supported_files = supported_files

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
    scoped_cfg = deepcopy(user_cfg)
    if maintenance is not None:
        if maintenance.root.resolve() != run_dir.resolve():
            raise ValueError('The processing plan belongs to a different run directory.')
        scoped_cfg = execution_config(scoped_cfg, maintenance)
    if convert_only:
        for step_name in WORKFLOW_ORDER:
            if step_name in scoped_cfg:
                scoped_cfg[step_name]["enabled"] = step_name == "convert"
        if force_conversion:
            scoped_cfg["convert"].setdefault("params", {})["overwrite"] = True
    upgrade_states = None
    if upgrading:
        scoped_cfg, upgrade_states = upgrade_execution_config(run_dir, scoped_cfg, cfg_path)
        origins = {state.original_image for state in upgrade_states}
        supported_files = sorted(origins)
    report = inspect_run(run_dir, scoped_cfg)
    if maintenance is not None:
        report = replace(report,
                         states=tuple(state for state in report.states if state.workdir in maintenance.scope),
                         records=tuple(record for record in report.records if record.path.parent in maintenance.scope),
                         )
        # The caller already displayed and accepted this exact processing plan.
        # Do not broaden it via the normal overwrite cascade or another prompt.
        effective_cfg = scoped_cfg
    if upgrade_states is not None:
        scope = {state.workdir for state in upgrade_states}
        report = replace(report,
                         states=tuple(upgrade_states),
                         records=tuple(record for record in report.records if record.path.parent in scope),
                         rebuild_outputs=tuple(item for item in report.rebuild_outputs if item[1].parent in scope),
                         )
    effective_cfg = scoped_cfg
    retain_legacy = False
    if maintenance is not None:
        pass
    elif report.needs_decision:
        if artifact_decision is not None:
            decision = artifact_decision(report)
        elif interaction is not None:
            decision = interaction.decide_artifacts(report)
        else:
            raise PreflightRequired(report)
        scoped_cfg = apply_decision(scoped_cfg, report, decision)
        if decision == "rebuild":
            supported_files = sorted(set(supported_files) | {state.original_image for state in report.states})
            retain_legacy = report.legacy
        effective_cfg = (apply_overwrite_cascade(scoped_cfg, WORKFLOW_ORDER)
                         if decision == "rebuild" else scoped_cfg)
    else:
        effective_cfg = apply_overwrite_cascade(scoped_cfg, WORKFLOW_ORDER)

    raw_report = None
    if effective_cfg.get("convert", {}).get("enabled", False):
        labels = effective_cfg.get("convert", {}).get("params", {}).get("channel_labels") or ()
        raw_report = inspect_raw_inputs(run_dir, sorted(set(all_supported_files) | set(supported_files)),
                                       channel_labels=[labels] if isinstance(labels, str) else labels,
                                       )
        if raw_report.problems:
            raise ValueError(raw_report.describe())

    # --- build ExperimentState list from saved states + newly discovered raw files ---
    if maintenance is not None:
        states = [replace(state, execution_scope=maintenance.scope)
                  for state in discover_saved_states(run_dir) if state.workdir in maintenance.scope]
        # A conversion reads all series once. Its runner preserves unscheduled
        # siblings and merges newly built arrays into their existing state.
        convert_origins = {state.original_image for state in states
                           if 'convert' in maintenance.scope[state.workdir]}
        seen = set()
        unique = []
        for state in sorted(states, key=lambda item: 'convert' not in maintenance.scope[item.workdir]):
            if state.original_image in convert_origins:
                if state.original_image in seen:
                    continue
                seen.add(state.original_image)
            unique.append(state)
        states = unique
    else:
        states = assemble_experiment_states(run_dir, supported_files, effective_cfg, user_name)
    if upgrade_states is not None:
        origins = {state.original_image for state in upgrade_states}
        states = [state for state in states if state.original_image in origins]
    if raw_report is not None:
        states = [replace(state, acquisition_directory=raw_report.acquisition_directories.get(state.original_image))
                  for state in states]
    # Manual drawing and older tools consume the generic image alias. Bind it
    # to the same enabled chain as the configured StepProfiles, including when
    # every preprocessing step is bypassed and no image step runs this launch.
    image_role = ARTI_IMG_RAW
    for step, role in IMAGE_OUTPUTS.items():
        if effective_cfg.get(step, {}).get("enabled", False):
            image_role = role
    states = [replace(state, artifacts={**state.artifacts, ARTI_IMG: state.artifacts[image_role]})
              if image_role in state.artifacts else state for state in states]
    overwrite_scope = {state.workdir: tuple(step for step in WORKFLOW_ORDER
                       if effective_cfg.get(step, {}).get('enabled')
                       and effective_cfg[step].get('params', {}).get('overwrite')) for state in report.states}
    replaced = replacement_states(report.states, overwrite_scope) if maintenance is None and not retain_legacy else []
    require_pipeline_space(run_dir, states, effective_cfg, additional_bytes=rebuild_backup_size(replaced))
    if replaced:
        retain_rebuild_backups(run_dir, replaced)
    if retain_legacy:
        preserve_replaced_results(report)

    # --- logging setup once ---
    log_path = configure_logging(log_dir=log_dir,
                                 console_level=console_level,
                                 file_level=file_level,
                                 console_handler=console_handler,
                                 )

    # Save the user's full configuration before execution or temporary run
    # overrides, so the GUI can reopen this run even if processing fails.
    saved_settings = save_run_settings(cfg_path, run_dir)
    logger.info("Run settings saved to %s", saved_settings)

    run_progress = run_progress if run_progress is not None else RunProgress()

    def save_progress_report() -> None:
        """
        Save progress report.
        """
        if log_path is None:
            return
        timestamp = log_path.stem.removeprefix("fits_")
        ensure_fits_directory(report_dir)
        report_path = report_dir / f"fits_report_{timestamp}.txt"
        report_path.write_text(format_run_report(run_progress, run_dir, include_header=True) + "\n",
                               encoding="utf-8",
                               )
        logger.info("Full pipeline report saved to %s", report_path)

    # --- start the workflow ---
    try:
        if convert_only and not any(effective_cfg.get(step, {}).get("enabled", False)
                                    for step in WORKFLOW_ORDER if step != "convert"):
            logger.info("Starting conversion-only execution.")
            final_states = run_conversion_only(effective_cfg,
                                               states,
                                               step_delay_seconds=demo_step_delay,
                                               progress=run_progress,
                                               )
        elif interaction is not None and interactive_inputs_requested(effective_cfg):
            logger.info("Starting interactive workflow for manual inputs.")
            final_states = run_interactive_workflow(effective_cfg,
                                                    states,
                                                    interaction,
                                                    step_delay_seconds=demo_step_delay,
                                                    progress=run_progress,
                                                    )
        else:
            match rt_mode:
                case "batch":
                    logger.info("Starting batch execution of workflow")
                    final_states = run_batch_workflow(effective_cfg,
                                                      states,
                                                      run_progress=run_progress,
                                                      terminal_progress=terminal_progress,
                                                      )
                case "conveyor":
                    logger.info("Starting conveyor execution of workflow")
                    final_states = run_workflow_scheduler(effective_cfg,
                                                          states,
                                                          run_progress=run_progress,
                                                          terminal_progress=terminal_progress,
                                                          )
    except BaseException:
        run_progress.skip_unfinished()
        save_progress_report()
        raise

    # --- log final states ---
    for st in final_states:
        logger.debug("Final state: exp_id=%s last_step=%s", st.experiment_id, st.last_step)
        try:
            refresh_branches(st)
        except ValueError as error:
            logger.warning("REF/ROI review required: %s", error)

    # Regenerate whole-run masters even when only outdated acquisitions needed rebuilding.
    aggregate_states = final_states
    if upgrading or maintenance is not None:
        aggregate_states = discover_saved_states(run_dir)
    try:
        aggregate_quantification(effective_cfg, aggregate_states, run_dir)
        aggregate_distance_profiles(effective_cfg, aggregate_states, run_dir)
    finally:
        save_progress_report()

    logger.info("Pipeline finished with %d final experiment states", len(final_states))
