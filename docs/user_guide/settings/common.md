# Shared processing settings

[Guide home](../README.md)

Related: [Main GUI](../runs_and_settings.md) · [File management](../reprocessing_and_file_management.md)

Use these controls consistently across the main settings tabs.

| Control | What it does |
| --- | --- |
| Include in workflow | Include this step in processing and input selection. Bypassing a step also bypasses its saved output as a source. |
| Overwrite | Recompute an included step even if a completed result exists. Review affected downstream results before proceeding. |
| Execution | Experiment-level execution strategy; keep the defaults unless you need to change resource use. |
| Workers | Maximum experiment workers; automatic/None delegates the count to the executor. |

These are settings for the next run. **Save settings** persists the draft without
processing; **Run pipeline** saves and runs the included workflow. Preview tools
have their own save actions and do not process the full dataset.
