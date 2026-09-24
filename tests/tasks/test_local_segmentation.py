from __future__ import annotations

import numpy as np
from skimage.draw import disk

from fits.tasks.tracking.mask_prediction import (
    AddEditPredictor,
    SplitPredictor,
    combine_auxiliary_masks,
    mask_agreement,
)


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
    assert proposal.method == "guided_image_watershed"


def _cell_plane(center: tuple[int, int], *, intensity: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    image = np.zeros((80, 80), dtype=np.float32)
    labels = np.zeros((80, 80), dtype=np.uint16)
    rows, columns = disk(center, 9, shape=image.shape)
    image[rows, columns] = intensity
    labels[rows, columns] = 1
    image += np.random.default_rng(sum(center)).normal(0, 0.03, image.shape)
    return image, labels


def test_local_model_learns_existing_masks_and_refines_with_points() -> None:
    training = [_cell_plane(center) for center in ((20, 20), (40, 30), (58, 55))]
    model = AddEditPredictor(maximum_samples_per_class=8_000)
    model.fit([item[0] for item in training], [item[1] for item in training])
    image, expected = _cell_plane((38, 46))

    first = model.predict(image, [(38, 46)])

    y0, y1, x0, x1 = first.bounds
    expected_crop = expected[y0:y1, x0:x1] != 0
    intersection = np.count_nonzero(first.mask & expected_crop)
    union = np.count_nonzero(first.mask | expected_crop)
    assert first.mask[38 - y0, 46 - x0]
    assert intersection / union > 0.75

    refined = model.predict(image, [(38, 46)], [(38, 52)])
    ry0, _, rx0, _ = refined.bounds
    assert refined.mask[38 - ry0, 46 - rx0]
    assert not refined.mask[38 - ry0, 52 - rx0]

    temporal = model.predict(
        image, [(38, 46)], temporal_mask=expected != 0, temporal_weight=0.9)
    assert temporal.temporal_weight == 0.9
    assert np.mean(temporal.probability[expected_crop]) > np.mean(
        first.probability[expected_crop])

    drawn = expected != 0
    drawn[37:40, 53:61] = True
    corrected = model.predict(
        image, [(38, 46)], [(38, 58)], initial_mask=drawn)
    cy0, _, cx0, _ = corrected.bounds
    corrected_expected = expected[
        corrected.bounds[0]:corrected.bounds[1],
        corrected.bounds[2]:corrected.bounds[3]] != 0
    assert np.count_nonzero(corrected.mask & corrected_expected) > 0.9 * np.count_nonzero(
        corrected_expected)
    assert not corrected.mask[38 - cy0, 58 - cx0]


def test_auxiliary_mask_reliability_rewards_agreement_and_combines_softly() -> None:
    target = np.zeros((20, 20), dtype=np.uint8)
    target[5:15, 5:15] = 1
    matching = target.copy()
    unrelated = np.zeros_like(target)
    unrelated[:4, :4] = 1

    assert mask_agreement([target], [matching]) == 1.0
    assert mask_agreement([target], [unrelated]) == 0.0
    combined, confidence = combine_auxiliary_masks(
        [matching != 0, unrelated != 0], [0.9, 0.05])

    assert combined is not None
    assert combined[10, 10]
    assert not combined[1, 1]
    assert np.isclose(confidence, 0.475)


def test_local_model_can_bootstrap_an_empty_session_from_a_click() -> None:
    image, expected = _cell_plane((35, 42))
    model = AddEditPredictor(maximum_samples_per_class=8_000)

    model.fit_from_prompts(image, [(35, 42)], [], expected_diameter=18)
    proposal = model.predict(image, [(35, 42)])

    y0, y1, x0, x1 = proposal.bounds
    expected_crop = expected[y0:y1, x0:x1] != 0
    assert proposal.mask[35 - y0, 42 - x0]
    assert np.count_nonzero(proposal.mask & expected_crop) > 0.7 * np.count_nonzero(expected_crop)


def test_positive_click_strongly_favours_inside_a_drawn_border() -> None:
    training = [_cell_plane(center) for center in ((20, 20), (40, 30), (58, 55))]
    model = AddEditPredictor(maximum_samples_per_class=8_000)
    model.fit([item[0] for item in training], [item[1] for item in training])
    image = np.zeros((80, 80), dtype=np.float32)
    border = np.zeros_like(image, dtype=bool)
    border[28, 28:53] = True
    border[52, 28:53] = True
    border[28:53, 28] = True
    border[28:53, 52] = True

    proposal = model.predict(image, [(40, 40)], initial_mask=border)

    y0, _, x0, _ = proposal.bounds
    interior = proposal.mask[30 - y0:51 - y0, 30 - x0:51 - x0]
    assert np.mean(interior) > 0.9


def test_prompt_similarity_reaches_matching_pixels_beyond_click_radius() -> None:
    features = np.zeros((20, 20, 3), dtype=np.float64)
    features[12:, :, :] = 4.0

    similarity = AddEditPredictor._prompt_feature_similarity(
        features, 3, 3)

    assert similarity[3, 3] == 1.0
    assert similarity[9, 16] > 0.99
    assert similarity[16, 16] < 0.01
