from __future__ import annotations

import time

import pytest

from fits.workflows.runtime.batch.workers import execute_items


def test_execute_items_serially_runs_in_input_order() -> None:
    out = list(execute_items(
        [1, 2, 3], lambda item: item * 2, mode='serial'))

    assert out == [2, 4, 6]


def test_execute_items_with_ordered_threads_preserves_input_order() -> None:
    def slow_identity(item: int) -> int:
        time.sleep(0.01 * (4 - item))
        return item

    out = list(execute_items(
        [1, 2, 3], slow_identity, mode='thread', workers=2, ordered=True))

    assert out == [1, 2, 3]


def test_execute_items_unordered_wraps_item_failure() -> None:
    def maybe_fail(item: int) -> int:
        if item == 2:
            raise ValueError('boom')
        return item

    with pytest.raises(RuntimeError, match='Task failed for item: 2'):
        list(execute_items(
            [1, 2, 3], maybe_fail, mode='thread', workers=2, ordered=False))


def test_execute_items_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError, match='Invalid mode'):
        list(execute_items([1], lambda item: item, mode='bad-mode'))
