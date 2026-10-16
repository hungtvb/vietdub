"""Fast unit checks for actual app ASR integration (no fake model claims)."""
from asr.whisper_align import associate_aligned_words
from asr.whisper_pyannote_adapter import construct_segments, assign_speaker


def _raw(words, aligned=True):
    return {
        "id": 5, "start": 0.0, "end": 3.0, "text": "Hello! Hi!",
        "avg_logprob": -.2, "no_speech_prob": .01,
        "alignment_status": "whisperx_aligned" if aligned else "whisper_words_unaligned",
        "words": words
    }


def test_align_matches_timestamps_when_whisperx_drops_an_input_segment():
    originals = [
        {"start": 0., "end": 1., "text": "hello"},
        {"start": 1., "end": 2., "text": "!"},
        {"start": 2., "end": 3., "text": "goodbye"},
    ]
    returned = [{"words": [
        {"start": .2, "end": .9, "word": "hello"},
        {"start": 2.1, "end": 2.8, "word": "goodbye"}]}]
    mapped = associate_aligned_words(originals, returned)
    assert len(mapped) == 3
    assert [len(x) for x in mapped] == [1, 0, 1]


def test_two_speakers_in_one_whisper_segment_are_split():
    evidence = [_raw([
        {"start": .1, "end": .8, "word": "Hello!"},
        {"start": 1.5, "end": 2.2, "word": " Hi!"}
    ])]
    windows = [{"start": 0., "end": 1., "label": "S1"},
               {"start": 1.3, "end": 3., "label": "S2"}]
    segments, qa, mapping = construct_segments(evidence, windows)
    assert len(segments) == 2
    assert [x.speaker for x in segments] == [0, 1]
    assert [s.text_src for s in segments] == ["Hello!", "Hi!"]
    assert len(qa) == len(segments)
    assert set(mapping) == {"S1", "S2"}


def test_missing_speaker_is_not_assumed_approved():
    evidence = [_raw([{"start": 3., "end": 4., "word": "Help!"}])]
    segments, qa, _ = construct_segments(evidence, [
        {"start": 0., "end": 1., "label": "S1"}])
    assert len(segments) == 1
    assert segments[0].needs_review
    assert qa[0]["speaker_label"] == "UNKNOWN"


def test_unaligned_words_are_review_required():
    evidence = [_raw([{"start": .2, "end": 1.2, "word": "Test"}], aligned=False)]
    segments, qa, _ = construct_segments(evidence, [
        {"start": 0., "end": 2., "label": "A"}])
    assert segments[0].needs_review
    assert qa[0]["alignment_status"] == "whisper_words_unaligned"


def test_speaker_overlap_uses_independent_pyannote_windows():
    label, coverage, share = assign_speaker(1., 2., [
        {"start": .5, "end": 1.75, "label": "A"},
        {"start": 1.75, "end": 2.5, "label": "B"}])
    assert label == "A"
    assert .7 <= coverage <= .8
    assert .7 <= share <= .8
