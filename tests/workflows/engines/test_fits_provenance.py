from fisch.environment.constant import StepName
from fisch.workflows.metadata import PipelineMetadata


def test_proc_metadata_records_run_and_step_provenance() -> None:
    metadata = PipelineMetadata.init(user_name="ben").with_step(
        step_name=StepName.CONVERT,
        created_by="fits-io",
        exported_channel="all",
        params={"z_projection": "max"},)

    payload = metadata.to_dict()
    assert payload["pipeline_meta"]["user_name"] == "ben"
    assert payload["steps"][StepName.CONVERT]["created_by"] == "fits-io"
    assert payload["steps"][StepName.CONVERT]["params"]["z_projection"] == "max"
    assert payload["steps"][StepName.CONVERT]["version"]
    assert payload["steps"][StepName.CONVERT]["timestamp"]
