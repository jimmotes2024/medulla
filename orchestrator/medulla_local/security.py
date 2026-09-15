"""Local credential files and a single-writer service lock (macOS/Linux)."""

import fcntl
import os
import secrets
from pathlib import Path


def private_write(path, content):
    """Create a new private file, refusing symlinks and overwrites."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def credential(path):
    path = Path(path)
    if not path.exists():
        private_write(path, secrets.token_urlsafe(32))
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('Credential must be a private regular file')
    return path.read_text().strip()


class StateLock:
    """Held for the service lifetime. Never kills another process or steals its lock."""

    def __init__(self, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.stat().st_mode & 0o077:
            raise ValueError('State directory must have mode 0700')
        fd = os.open(directory / 'service.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.stream = os.fdopen(fd, 'w')
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            raise ValueError('This state directory already has an active coordinator') from None

    def close(self):
        self.stream.close()
