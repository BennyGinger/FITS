from __future__ import annotations
import os
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from typing import TypeVar

from fits.environment.constant import ExecMode


T = TypeVar("T")
R = TypeVar("R")


def _default_workers(mode: ExecMode) -> int:
    cpu = os.cpu_count() or 1
    if mode == "thread":
        return min(32, cpu + 4)
    if mode == "process":
        return max(1, cpu)
    return 1


def execute(items: Sequence[T], func: Callable[[T], R], *, mode: ExecMode = "serial", workers: int | None = None, ordered: bool = False, ) -> Iterator[R]:
    """
    Execute func over items in serial / threads / processes.

    - ordered=False yields results as tasks complete (best for progress).
    - ordered=True yields results in the same order as `items`.
    - Fail-fast: the first exception raised by any task is propagated.
    """
    if mode == "serial":
        for it in items:
            yield func(it)
        return

    if mode not in ("thread", "process"):
        raise ValueError(f"Invalid mode: {mode!r}")

    n_workers = _default_workers(mode) if workers is None else workers
    Exec = ThreadPoolExecutor if mode == "thread" else ProcessPoolExecutor

    with Exec(max_workers=n_workers) as ex:
        if ordered:
            futures = [ex.submit(func, it) for it in items]
            for fut in futures:
                yield fut.result()
        else:
            future_to_item = {ex.submit(func, it): it for it in items}
            for fut in as_completed(future_to_item):
                try:
                    yield fut.result()
                except Exception as e:
                    item = future_to_item[fut]
                    raise RuntimeError(f"Task failed for item: {item!r}") from e

if __name__ == '__main__':
    print(os.cpu_count())