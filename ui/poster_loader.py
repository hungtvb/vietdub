"""Load FFmpeg poster images without blocking the Qt event loop."""
from __future__ import annotations

from queue import Empty, SimpleQueue
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Signal

from media.thumbnail import poster_for


def _make_poster(video: str, cache_dir: str,
                 results: SimpleQueue[tuple[str, str]]) -> None:
    try:
        result = poster_for(video, cache_dir)
        results.put((video, str(result) if result else ""))
    except Exception:  # noqa: BLE001 - preview is optional
        results.put((video, ""))


class PosterLoader(QObject):
    ready = Signal(str, str)  # source video, poster path (empty on failure)

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self._results: SimpleQueue[tuple[str, str]] = SimpleQueue()
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def request(self, video: str, cache_dir: str) -> None:
        Thread(target=_make_poster,
               args=(video, cache_dir, self._results), daemon=True).start()

    def stop(self) -> None:
        self._timer.stop()

    def _drain(self) -> None:
        while True:
            try:
                source, path = self._results.get_nowait()
            except Empty:
                break
            self.ready.emit(source, path)
