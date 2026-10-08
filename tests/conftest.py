# VietDub tests - shared fixtures
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project.schema import Segment, Speaker  # noqa: E402


def make_segments(n=4, speakers=(0, 1)):
    segs = []
    for i in range(n):
        segs.append(Segment(
            index=i, start=float(i * 5), end=float(i * 5 + 4),
            speaker=speakers[i % len(speakers)],
            gender="female" if speakers[i % len(speakers)] == 0 else "male",
            text_src=f"这是第{i}句话",
            text_vi=f"Đây là câu thứ {i}",
            confidence=0.95))
    return segs


def make_speakers():
    return {0: Speaker(id=0, gender="female", confidence=0.9),
            1: Speaker(id=1, gender="male", confidence=0.9)}


@pytest.fixture
def segments():
    return make_segments()


@pytest.fixture
def speakers():
    return make_speakers()


@pytest.fixture
def job_dir(tmp_path):
    d = tmp_path / "jobs" / "testjob"
    (d / "stages").mkdir(parents=True)
    return d


class FakeTranslator(__import__("translation.base", fromlist=["BaseTranslator"]).BaseTranslator):
    """Mock provider returning canned _chat replies (script list)."""
    name = "fake"

    def __init__(self, script=None):
        super().__init__()
        self.script = script or []
        self.calls = 0

    def _chat(self, system, user):
        self.last_system = system
        self.last_user = user
        r = self.script[self.calls] if self.calls < len(self.script) \
            else (self.script[-1] if self.script else "{}")
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return r
