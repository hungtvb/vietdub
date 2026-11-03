"""Fast unit checks for actual app ASR integration (no fake model claims)."""
from asr.whisper_align import (associate_aligned_words, aligned_words_cover_source,
                               forced_align)
from asr.whisper_pyannote_adapter import construct_segments, assign_speaker


def _raw(words, aligned=True, text="Hello! Hi!"):
    return {
        "id": 5, "start": 0.0, "end": 3.0, "text": text,
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
    evidence = [_raw([{"start": .2, "end": 1.2, "word": "Test"}],
                     aligned=False, text="Test")]
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


def test_partial_word_timing_keeps_full_transcript_and_requires_review():
    # Previously "Hi!" was silently discarded by the word loop.
    evidence = [_raw([
        {"start": .1, "end": .8, "word": "Hello!"},
        {"start": None, "end": 2.2, "word": " Hi!"}
    ])]
    windows = [{"start": 0., "end": 3., "label": "S1"}]
    segments, qa, mapping = construct_segments(evidence, windows)
    assert len(segments) == 1
    assert segments[0].text_src == "Hello! Hi!"
    assert segments[0].needs_review is True
    assert segments[0].speaker == len(mapping)  # UNKNOWN, not guessed S1
    assert qa[0]["alignment_status"] == "incomplete_word_timing"
    assert "Invalid word positions" in qa[0]["timing_warning"]


def test_nan_word_timing_is_not_treated_as_valid_alignment():
    evidence = [_raw([
        {"start": .1, "end": .8, "word": "Hello!"},
        {"start": float("nan"), "end": 2.2, "word": " Hi!"}
    ])]
    segments, qa, _ = construct_segments(evidence, [
        {"start": 0., "end": 3., "label": "S1"}])
    assert segments[0].text_src == "Hello! Hi!"
    assert segments[0].needs_review
    assert qa[0]["alignment_status"] == "incomplete_word_timing"


def test_invalid_parent_timing_rejects_unrecoverable_partial_alignment():
    import pytest
    original = _raw([{"start": None, "end": 2.2, "word": "Hi!"}])
    original["end"] = float("nan")
    with pytest.raises(RuntimeError, match="invalid source timing"):
        construct_segments([original], [{"start": 0., "end": 3., "label": "S1"}])


def test_alignment_lexical_coverage_ignores_punctuation_not_missing_words():
    assert aligned_words_cover_source(
        "Xin chào, thế giới!", [
            {"word": "Xin "}, {"word": "chào"}, {"word": " thế giới"}])
    assert not aligned_words_cover_source(
        "Hello! Hi!", [{"word": "Hello!"}])


def test_valid_timestamps_but_missing_word_restore_full_utterance():
    evidence = [_raw([{"start": .1, "end": .8, "word": "Hello!"}])]
    segments, qa, mapping = construct_segments(evidence, [
        {"start": 0., "end": 3., "label": "S1"}])
    assert len(segments) == 1
    assert segments[0].text_src == "Hello! Hi!"
    assert segments[0].needs_review
    assert segments[0].speaker == len(mapping)  # UNKNOWN, not guessed
    assert qa[0]["alignment_status"] == "incomplete_alignment"
    assert "omit lexical content" in qa[0]["timing_warning"]


def test_whisperx_partial_result_is_rejected_before_diarization(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    # WhisperX can omit a token and still return plausible aligned timestamps.
    fake = SimpleNamespace(
        load_audio=lambda path: object(),
        load_align_model=lambda **kwargs: (object(), {}),
        align=lambda items, model, metadata, audio, device,
                     return_char_alignments: {
            "segments": [{"words": [
                {"start": .1, "end": .8, "word": "Hello!"}]}],
        },
    )
    monkeypatch.setitem(sys.modules, "whisperx", fake)
    raw = [{**_raw([
        {"start": .1, "end": .8, "word": "Hello!"},
        {"start": 1.2, "end": 2.2, "word": " Hi!"},
    ]), "language": "en"}]
    result, stats = forced_align(raw, tmp_path / "does-not-need-real-audio.wav")
    assert result[0]["alignment_status"] == "incomplete_alignment"
    assert result[0]["words"][0]["word"] == "Hello! Hi!"
    assert stats["aligned"] == 0
    assert stats["fallback_to_whisper_words"] == 1
    segments, qa, _ = construct_segments(result, [
        {"start": 0., "end": 3., "label": "S1"}])
    assert segments[0].text_src == "Hello! Hi!"
    assert segments[0].needs_review
    assert qa[0]["alignment_status"] == "incomplete_alignment"
