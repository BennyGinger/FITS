from fits.environment.constant import StepName
from fits.workflows.metadata.models import FitsMeta


def test_fits_metadata_adds_shared_step_parameters() -> None:
    metadata = FitsMeta.init(user_name="ben").with_step(
        step_name=StepName.BG_SUB,
        created_by="bg-sub",
        exported_channel="all",
        params={"sigma": 2.0},)

    step = metadata.to_dict()["steps"][StepName.BG_SUB]
    assert step["params"] == {"sigma": 2.0}
    assert step["channels"] == {}


def test_fits_metadata_adds_selected_channel_parameters() -> None:
    metadata = FitsMeta.init().with_step(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[1, 2],
        params={"diameter": 30},)

    channels = metadata.to_dict()["steps"][StepName.SEGMENT]["channels"]
    assert channels["1"]["diameter"] == 30
    assert channels["2"]["diameter"] == 30
