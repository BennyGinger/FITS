from fits.environment.constant import StepName
from fits.workflows.metadata import FitsMeta


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


def test_channel_setting_cannot_overwrite_numeric_channel_index() -> None:
    metadata = FitsMeta.init().with_step(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[1],
        params={"channel": "GFP", "diameter": 30},)

    serialized = metadata.to_dict()
    channel = serialized["steps"][StepName.SEGMENT]["channels"]["1"]

    assert channel["channel"] == 1
    assert channel["channel_label"] == "GFP"
    assert FitsMeta.from_dict(serialized).completed_channels(StepName.SEGMENT) == [1]


def test_legacy_channel_label_collision_is_loaded_from_mapping_key() -> None:
    serialized = FitsMeta.init().with_step(
        step_name=StepName.SEGMENT,
        created_by="cellpose-kit",
        exported_channel=[1],
        params={"diameter": 30},).to_dict()
    serialized["steps"][StepName.SEGMENT]["channels"]["1"]["channel"] = "GFP"

    restored = FitsMeta.from_dict(serialized)

    assert restored.completed_channels(StepName.SEGMENT) == [1]
    assert restored.steps[StepName.SEGMENT].channels["1"].params["channel_label"] == "GFP"
