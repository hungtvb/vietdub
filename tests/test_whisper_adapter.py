from types import SimpleNamespace

from asr.whisper_adapter import (WhisperDiarizationAdapter,
                                 merge_whisper_segments)
from project.schema import Segment


def test_merge_whisper_segments_uses_largest_campp_overlap_and_clips():
    diarization = [
        Segment(index=0, start=0.0, end=2.2, speaker=0, text_src="turn 0"),
        Segment(index=1, start=2.2, end=4.0, speaker=1, text_src="turn 1"),
    ]
    raw = [
        SimpleNamespace(start=1.0, end=2.0, text="  第一段。 ",
                        no_speech_prob=0.1, avg_logprob=-0.2),
        SimpleNamespace(start=2.5, end=5.0, text="第二段。",
                        no_speech_prob=0.7, avg_logprob=-1.2),
    ]

    got = merge_whisper_segments(raw, diarization, duration_sec=3.5)

    assert [(s.start, s.end, s.speaker, s.text_src) for s in got] == [
        (1.0, 2.0, 0, "第一段。"),
        (2.5, 3.5, 1, "第二段。"),
    ]
    assert got[0].needs_review is False
    assert got[1].needs_review is True


def test_merge_whisper_segments_drops_empty_and_invalid_intervals():
    raw = [
        SimpleNamespace(start=0, end=1, text="   "),
        SimpleNamespace(start=2, end=2, text="bad timestamp"),
        SimpleNamespace(start=4, end=5, text="past end"),
    ]

    assert merge_whisper_segments(raw, [], duration_sec=3.0) == []


def test_whisper_adapter_maps_transcript_and_unloads_model(monkeypatch, tmp_path):
    class Diarizer:
        _pipe = None

        def transcribe(self, _path):
            return [Segment(index=0, start=0, end=2, speaker=3,
                            text_src="speaker turn")]

    class Pipe:
        def transcribe(self, *_args, **_kwargs):
            self.kwargs = _kwargs
            return ([SimpleNamespace(start=0.2, end=1.0, text="你好。",
                                     no_speech_prob=0.0, avg_logprob=-0.2)],
                    SimpleNamespace(language="zh", language_probability=0.99))

    import asr.whisper_adapter as module
    monkeypatch.setattr(module, "_wav_duration_sec", lambda _path: 2.0)
    monkeypatch.setattr(module, "_models_dir", lambda: tmp_path)
    pipe = Pipe()
    adapter = WhisperDiarizationAdapter(
        asr_model="unused", vad_model="unused", punc_model="unused",
        spk_model="unused", diarizer=Diarizer(),
        source_language="Chinese", proper_nouns=["黑神话", "Robo Cup"],
        model_factory=lambda *_args, **_kwargs: pipe)

    got = adapter.transcribe(tmp_path / "audio.wav")

    assert len(got) == 1
    assert got[0].text_src == "你好。"
    assert got[0].speaker == 3
    assert adapter._pipe is None
    assert pipe.kwargs["language"] == "zh"
    assert pipe.kwargs["vad_filter"] is False
    assert pipe.kwargs["initial_prompt"] == "常见专名：黑神话、Robo Cup"


def test_whisper_language_auto_uses_model_detection():
    assert WhisperDiarizationAdapter._normalize_language("auto") is None
    assert WhisperDiarizationAdapter._normalize_language("中文") == "zh"
