"""ASR long-video regression: preserve all words around 10-minute-like edges.

Synthetic PCM is only the input container; transcript windows are controlled
unit evidence to test chunk ownership and overlap without downloading models.
"""
from pathlib import Path
import shutil

import numpy as np
import pytest
import soundfile as sf

import asr.funasr_adapter as fa
from project.schema import Segment


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="requires ffmpeg")
def test_padded_chunks_preserve_boundary_utterance_once(tmp_path, monkeypatch):
    wav = tmp_path / "long.wav"
    sf.write(str(wav), np.zeros(12 * 16000, dtype=np.float32), 16000)
    monkeypatch.setattr(fa, "ASR_CHUNK_SEC", 5.0)
    adapter = fa.FunASRAdapter("a", "v", "p", "s", chunk_overlap_sec=1.)
    adapter.load = lambda: None

    calls = []
    def pretend_model(path):
        ci = int(Path(path).stem.split("_")[-1])
        calls.append(ci)
        if ci == 0:
            # B is included in right-hand padding but should belong to chunk 1.
            spans = [(1., 2., "A"), (4.5, 5.5, "B")]
        elif ci == 1:
            # Chunk 1 starts 1 sec early (absolute start=4).
            spans = [(.5, 1.5, "B"), (5., 6., "C"),
                     (5.5, 6.5, "D")]
        else:
            # Chunk 2 starts 1 sec early (absolute start=9).
            spans = [(.5, 1.5, "D"), (1.8, 2.7, "E")]
        return [Segment(index=i, start=a, end=b, speaker=0,
                        text_src=text, source_lang="zh")
                for i, (a, b, text) in enumerate(spans)]

    monkeypatch.setattr(adapter, "_transcribe_one", pretend_model)
    segments = adapter.transcribe(wav)
    assert calls == [0, 1, 2]
    assert [s.text_src for s in segments] == ["A", "B", "C", "D", "E"]
    assert [round(s.start, 2) for s in segments] == [1., 4.5, 9., 9.5, 10.8]
    assert [round(s.end, 2) for s in segments] == [2., 5.5, 10., 10.5, 11.7]
    assert [s.index for s in segments] == list(range(5))
    assert len(set(s.speaker for s in segments)) == 3
    assert segments[2].needs_review and segments[3].needs_review
    assert adapter.metrics["chunk_count"] == 3
    assert adapter.metrics["boundary_review_count"] >= 3
    assert adapter.metrics["chunk_overlap_seconds"] == 1.


def test_nested_simultaneous_speech_keeps_all_spans():
    segments = [
        Segment(index=0, start=0., end=12., speaker=0, text_src="主角长台词"),
        Segment(index=1, start=2., end=3., speaker=1, text_src="插话一"),
        Segment(index=2, start=4., end=5., speaker=2, text_src="插话二")]
    out = fa.FunASRAdapter.post_fix(segments)
    assert len(out) == 3
    assert [s.end for s in out] == [12., 3., 5.]
    assert all(s.needs_review for s in out)


@pytest.mark.parametrize("bad", [-1., 15.1])
def test_bad_overlap_rejected(bad):
    with pytest.raises(ValueError, match="chunk_overlap_sec"):
        fa.FunASRAdapter("a", "v", "p", "s", chunk_overlap_sec=bad)
