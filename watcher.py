import logging
from pathlib import Path

from db import Database

log = logging.getLogger(__name__)

VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.ts'}
AUDIO_EXTS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.opus'}
ALL_EXTS   = VIDEO_EXTS | AUDIO_EXTS


class Watcher:
    """
    Scans a source directory for new, stable media files not yet processed.

    Uses a two-phase stability check: a file is only yielded after two
    consecutive scans show the same file size, ensuring writes are complete.
    Since the minimum poll interval is 60s, this trivially satisfies the
    5-second stability requirement from the spec.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._pending: dict[str, int] = {}  # path → size at first sight

    def scan(self, source_dir: str) -> list[str]:
        """Return paths of files that are stable and not yet processed."""
        src = Path(source_dir)
        if not src.is_dir():
            log.warning('Source directory does not exist: %s', source_dir)
            return []

        current: dict[str, int] = {}
        for entry in src.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in ALL_EXTS:
                continue
            try:
                current[str(entry)] = entry.stat().st_size
            except OSError:
                continue

        stable: list[str] = []

        for path_str, size in current.items():
            if path_str in self._pending:
                if self._pending[path_str] == size:
                    # Size stable between two scans — check DB
                    del self._pending[path_str]
                    try:
                        mtime = Path(path_str).stat().st_mtime
                    except OSError:
                        continue
                    if not self._db.is_processed(path_str, mtime):
                        log.debug('Stable new file: %s', path_str)
                        stable.append(path_str)
                else:
                    # Still changing
                    self._pending[path_str] = size
            else:
                # First sighting
                self._pending[path_str] = size

        # Remove entries for files that disappeared between scans
        gone = set(self._pending) - set(current)
        for p in gone:
            del self._pending[p]

        return stable
