from fits.environment.constant import StepName
from fits.workflows.metadata.models import StepsMetadata


def test_step_metadata_preserves_existing_channels_when_updated() -> None:
    metadata = StepsMetadata.create(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[0],
        params={"diameter": 20},)
    updated = metadata.with_params(
        exported_channel=[1], params={"diameter": 30})

    assert updated.channels["0"].params == {"diameter": 20}
    assert updated.channels["1"].params == {"diameter": 30}
