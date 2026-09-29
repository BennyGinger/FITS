from __future__ import annotations

import sys
from types import ModuleType

import numpy as np
from fits.tasks.segmentation.local_seg import (
    MicroSamPredictor,
    SplitPredictor,
    component_at_point,
    fill_clicked_enclosure,
    fill_enclosed_mask,
    remove_clicked_component,
)


def test_microsam_adapter_integrates_with_upstream_inference_api(
    monkeypatch,
) -> None:
    """Preserve the upstream API contract used by the Add/Edit experiment."""
    calls = {}
    predictor = object()
    fake_util = ModuleType("micro_sam.util")
    fake_prompts = ModuleType("micro_sam.prompt_based_segmentation")

    def get_sam_model(*, model_type, device):
        calls["model"] = (model_type, device)
        return predictor

    def precompute_image_embeddings(model, image, **kwargs):
        calls["embedding"] = (model, image.copy(), kwargs)
        return {"crop_shape": image.shape}

    def segment_from_points(
        model, points, labels, *, image_embeddings,
        multimask_output, return_all,
    ):
        calls["prompt"] = (
            model, points.copy(), labels.copy(), image_embeddings,
            multimask_output, return_all,
        )
        mask = np.ones((1, *image_embeddings["crop_shape"]), dtype=bool)
        logits = np.zeros((1, 256, 256), dtype=np.float32)
        return mask, np.asarray([0.9]), logits

    fake_util.get_sam_model = get_sam_model
    fake_util.precompute_image_embeddings = precompute_image_embeddings
    fake_prompts.segment_from_points = segment_from_points
    monkeypatch.setitem(sys.modules, "micro_sam.util", fake_util)
    monkeypatch.setitem(
        sys.modules, "micro_sam.prompt_based_segmentation", fake_prompts)

    backend = MicroSamPredictor()
    image = np.zeros((60, 60), dtype=np.float32)
    proposal = backend.predict(
        image, [(30, 31)], [(32, 34)], expected_diameter=10,
        prediction_context=(7, 0, 0, 0),
    )

    y0, y1, x0, x1 = proposal.bounds
    assert calls["model"] == ("vit_t_lm", "cpu")
    assert calls["embedding"][0] is predictor
    assert calls["embedding"][1].shape == (y1 - y0, x1 - x0)
    assert calls["embedding"][2] == {"ndim": 2, "verbose": False}
    assert calls["prompt"][0] is predictor
    assert np.array_equal(
        calls["prompt"][1], [[30 - y0, 31 - x0], [32 - y0, 34 - x0]])
    assert np.array_equal(calls["prompt"][2], [1, 0])
    assert calls["prompt"][4:] == (False, True)
    assert proposal.mask.shape == (y1 - y0, x1 - x0)
    assert not proposal.mask[32 - y0, 34 - x0]


def test_microsam_reuses_the_active_crop_embedding(monkeypatch) -> None:
    backend = MicroSamPredictor()
    calls = []
    fake_util = ModuleType("micro_sam.util")

    def precompute(predictor, crop, **kwargs):
        calls.append((predictor, crop.copy(), kwargs))
        return {"features": "cached"}

    fake_util.precompute_image_embeddings = precompute
    monkeypatch.setitem(sys.modules, "micro_sam.util", fake_util)
    monkeypatch.setattr(backend, "_get_predictor", lambda: "predictor")
    crop = np.arange(25, dtype=np.float32).reshape(5, 5)

    first, first_reused = backend._get_embeddings(crop)
    second, second_reused = backend._get_embeddings(crop.copy())

    assert first is second
    assert not first_reused
    assert second_reused
    assert len(calls) == 1


def test_microsam_prepare_loads_the_model_without_prediction(monkeypatch) -> None:
    backend = MicroSamPredictor()
    loaded = []
    monkeypatch.setattr(
        backend, "_get_predictor", lambda: loaded.append(True) or object())

    backend.prepare()

    assert loaded == [True]


def test_microsam_smoke_backend_translates_prompts_and_masks_owners(
    monkeypatch,
) -> None:
    backend = MicroSamPredictor()
    embedding_calls = []
    prompt_calls = []

    def fake_embeddings(crop):
        embedding_calls.append(crop.copy())
        return "embedding", bool(len(embedding_calls) > 1)

    def fake_segment(predictor, points_yx, labels, embeddings):
        prompt_calls.append((points_yx.copy(), labels.copy(), embeddings))
        mask = np.ones((1, 25, 25), dtype=bool)
        return mask, np.asarray([0.9]), np.zeros((1, 1), dtype=float)

    monkeypatch.setattr(backend, "_get_embeddings", fake_embeddings)
    monkeypatch.setattr(backend, "_get_predictor", lambda: "predictor")
    monkeypatch.setattr(backend, "_segment_from_points", fake_segment)
    image = np.zeros((60, 60), dtype=np.float32)
    occupied = np.zeros_like(image, dtype=bool)
    excluded = np.zeros_like(image, dtype=bool)
    occupied[29, 29] = True
    excluded[31, 31] = True

    proposal = backend.predict(
        image, [(30, 30)], [(32, 33)], expected_diameter=10,
        occupied_mask=occupied, excluded_mask=excluded)

    y0, _, x0, _ = proposal.bounds
    assert np.array_equal(
        prompt_calls[0][0], [[30 - y0, 30 - x0], [32 - y0, 33 - x0]])
    assert np.array_equal(prompt_calls[0][1], [1, 0])
    assert not proposal.mask[29 - y0, 29 - x0]
    assert not proposal.mask[31 - y0, 31 - x0]
    assert not proposal.mask[32 - y0, 33 - x0]


def test_microsam_uses_previous_logits_for_same_crop_correction(monkeypatch) -> None:
    backend = MicroSamPredictor()
    embedding = object()
    point_calls = []
    refinement_calls = []
    monkeypatch.setattr(
        backend, "_get_embeddings", lambda crop: (embedding, bool(point_calls)))
    monkeypatch.setattr(backend, "_get_predictor", lambda: "predictor")

    def points(predictor, points_yx, labels, embeddings):
        point_calls.append(points_yx.copy())
        return (
            np.ones((1, 25, 25), dtype=bool), np.asarray([0.8]),
            np.full((1, 256, 256), 3.0, dtype=np.float32))

    def refine(predictor, points_yx, labels, embeddings, logits):
        refinement_calls.append(logits.copy())
        return (
            np.ones((1, 25, 25), dtype=bool), np.asarray([0.9]),
            np.full((1, 256, 256), 4.0, dtype=np.float32))

    monkeypatch.setattr(backend, "_segment_from_points", points)
    monkeypatch.setattr(backend, "_refine_from_logits", refine)
    image = np.zeros((60, 60), dtype=np.float32)
    context = (7, 2, 0, 0)

    backend.predict(
        image, [(30, 30)], expected_diameter=10,
        prediction_context=context)
    backend.predict(
        image, [(30, 30)], [(31, 34)], expected_diameter=10,
        prediction_context=context, continue_from_previous=True)

    assert len(point_calls) == 1
    assert len(refinement_calls) == 1
    assert np.all(refinement_calls[0] == 3.0)


def test_microsam_can_initialize_from_mask_without_a_click(monkeypatch) -> None:
    backend = MicroSamPredictor()
    captured = {}
    monkeypatch.setattr(backend, "_get_embeddings", lambda crop: ("embedding", False))
    monkeypatch.setattr(backend, "_get_predictor", lambda: "predictor")

    def from_mask(predictor, mask, points_xy, labels, embeddings):
        captured.update(points=points_xy, labels=labels, mask=mask.copy())
        return (
            mask[None], np.asarray([0.9]),
            np.ones((1, 256, 256), dtype=np.float32))

    monkeypatch.setattr(backend, "_segment_from_mask", from_mask)
    image = np.zeros((60, 60), dtype=np.float32)
    prior = np.zeros_like(image, dtype=bool)
    prior[25:36, 26:37] = True

    proposal = backend.predict(
        image, [], expected_diameter=16, initial_mask=prior,
        prediction_context=(7, 2, 0, 0))

    assert captured["points"] is None
    assert captured["labels"] is None
    assert np.any(proposal.mask)


def test_microsam_synchronizes_refinement_logits_to_displayed_mask(monkeypatch) -> None:
    backend = MicroSamPredictor()
    context = (7, 3, 0, 0)
    backend._prediction_context = context
    displayed = np.zeros((25, 25), dtype=bool)
    displayed[8:17, 9:18] = True
    expected_logits = np.full((256, 256), 5.0, dtype=np.float32)
    monkeypatch.setattr(
        backend, "_mask_to_logits", lambda mask: expected_logits.copy())

    assert backend.synchronize_mask(displayed, context)
    assert np.array_equal(backend._previous_logits, expected_logits)
    assert not backend.synchronize_mask(displayed, (8, 3, 0, 0))


def test_microsam_converts_displayed_mask_without_private_upstream_api() -> None:
    mask = np.zeros((40, 24), dtype=bool)
    mask[10:30, 7:18] = True

    logits = MicroSamPredictor._mask_to_logits(mask)

    assert logits.shape == (256, 256)
    assert np.max(logits) > 0
    assert np.min(logits) < 0


def test_split_predictor_clips_guidance_and_keeps_image_supported_gap() -> None:
    mask = np.zeros((40, 60), dtype=bool)
    mask[8:32, 8:52] = True
    image = np.ones(mask.shape, dtype=np.float32)
    image[:, 29:31] = 0.0
    guide = np.zeros(mask.shape, dtype=bool)
    guide[:, 30] = True

    proposal = SplitPredictor().predict(mask, image=image, guide=guide)

    assert set(np.unique(proposal.regions)) == {0, 1, 2}
    assert not np.any(proposal.regions[~mask])
    assert not np.any(proposal.gap[~mask])
    assert np.any(proposal.gap[:, 29:31])



def test_manual_fill_keeps_outline_and_fills_clicked_enclosure() -> None:
    outline = np.zeros((100, 100), dtype=bool)
    outline[28, 25:76] = True
    outline[72, 25:76] = True
    outline[28:73, 25] = True
    outline[28:73, 75] = True

    proposal = fill_enclosed_mask(
        outline, [(50, 50)], expected_diameter=20)
    predicted = np.zeros_like(outline)
    y0, y1, x0, x1 = proposal.bounds
    predicted[y0:y1, x0:x1] = proposal.mask

    assert np.all(predicted[outline])
    assert np.all(predicted[30:71, 27:74])
    assert not predicted[20, 20]


def test_manual_fill_respects_other_tracks_and_erased_pixels() -> None:
    outline = np.zeros((60, 60), dtype=bool)
    outline[15, 15:46] = True
    outline[45, 15:46] = True
    outline[15:46, 15] = True
    outline[15:46, 45] = True
    occupied = np.zeros_like(outline)
    occupied[28:33, 28:33] = True
    excluded = np.zeros_like(outline)
    excluded[20:24, 20:24] = True

    proposal = fill_enclosed_mask(
        outline, [(25, 25)], expected_diameter=20,
        occupied_mask=occupied, excluded_mask=excluded)
    y0, y1, x0, x1 = proposal.bounds

    assert not np.any(proposal.mask & occupied[y0:y1, x0:x1])
    assert not np.any(proposal.mask & excluded[y0:y1, x0:x1])


def test_click_fills_only_the_enclosed_background_region() -> None:
    mask = np.zeros((20, 30), dtype=bool)
    mask[3, 3:12] = True
    mask[11, 3:12] = True
    mask[3:12, 3] = True
    mask[3:12, 11] = True
    mask[3, 17:26] = True
    mask[11, 17:26] = True
    mask[3:12, 17] = True
    mask[3:12, 25] = True

    filled = fill_clicked_enclosure(mask, (7, 7))

    assert filled is not None
    assert np.all(filled[4:11, 4:11])
    assert not np.any(filled[4:11, 18:25])
    assert fill_clicked_enclosure(mask, (0, 0)) is None


def test_click_removes_only_the_selected_disconnected_component() -> None:
    mask = np.zeros((20, 30), dtype=bool)
    mask[3:10, 3:10] = True
    mask[5:12, 18:25] = True

    reduced = remove_clicked_component(mask, (7, 21))

    assert reduced is not None
    assert np.all(reduced[3:10, 3:10])
    assert not np.any(reduced[5:12, 18:25])
    assert remove_clicked_component(mask[0:12, 0:12], (7, 7)) is None


def test_component_at_point_selects_only_the_clicked_region() -> None:
    mask = np.zeros((12, 20), dtype=bool)
    mask[2:6, 2:6] = True
    mask[4:9, 12:17] = True

    selected = component_at_point(mask, (6, 14))

    assert not np.any(selected[2:6, 2:6])
    assert np.all(selected[4:9, 12:17])
    assert not np.any(component_at_point(mask, (0, 0)))
