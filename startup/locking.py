"""Small OS-backed leases, independent of FITS's installed dependencies."""

from pathlib import Path
import os


class BusyError(RuntimeError):
    """Another process owns this checkout's lease."""


class Lease:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if file.tell() == 0:
                    file.write(b" ")
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            file.close()
            raise BusyError("FITS or its updater is already using this checkout.") from error
        self.file = file
        return self

    def __exit__(self, *exception) -> None:
        if self.file is not None:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None
