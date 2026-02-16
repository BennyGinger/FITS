from __future__ import annotations

import logging
from time import sleep

from progress_bar.progress import ProgressManager


def main() -> None:
    # Smoke test: show a progress bar while logs may be emitted normally.
    logger = logging.getLogger("fits.smoke")
    logger.setLevel(logging.INFO)

    pm = ProgressManager.create()

    with pm:
        tid1 = pm.add_task("Processing exp_1", total=20)
        for i in range(20):
            if i % 5 == 0:
                logger.info("exp_1 step %s", i)
            pm.advance(tid1)
            sleep(0.2)

        tid2 = pm.add_task("Processing exp_2", total=10)
        for i in range(10):
            if i % 3 == 0:
                logger.info("exp_2 warn %s", i)
            pm.advance(tid2)
            sleep(0.25)


if __name__ == "__main__":
    main()
