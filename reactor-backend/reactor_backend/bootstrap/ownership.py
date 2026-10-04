"""Local process guard for the P1 single-worker deployment contract."""
from contextlib import contextmanager
import fcntl


@contextmanager
def single_worker(root):
    root.mkdir(parents=True,exist_ok=True)
    # Keep inode stable: unlinking while locked would permit another owner.
    with (root/'.reactor-backend.lock').open('a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('P1 requires one backend worker per workspace') from None
        try:
            yield
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)
