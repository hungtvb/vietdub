"""Deterministic regressions for Chinese cross-model comparison and honest QA."""
import pytest
import asr.chinese_comparison as cc


def test_punctuation_not_counted():
    assert cc.hanzi_only("你好，世界！ A123") == "你好世界"


def test_utterances_are_not_double_counted_at_window_boundaries():
    lines = [
        {"start": 0., "end": 9., "text_src": "你好"},
        {"start": 8.5, "end": 11.5, "text_src": "世界"},
    ]
    assert cc.extract_window(lines, 0., 10.) == "你好"
    assert cc.extract_window(lines, 10., 20.) == "世界"


def test_chinese_variant_normalization_changes_disagreement_measurement(monkeypatch):
    class DummyOpenCC:
        def convert(self, text):
            return text.translate(str.maketrans({"這": "这", "個": "个",
                                                  "學": "学", "說": "说"}))
    monkeypatch.setattr(cc, "_t2s_converter", lambda: DummyOpenCC())
    a = [{"start": 0., "end": 3., "text_src": "这个学校"}]
    b = [{"start": 0., "end": 3., "text": "這個學校"}]
    result = cc.compare_transcripts(a, b, duration=4., window_seconds=4.)
    assert result["raw_character_sequence_agreement"] < 1.
    assert result["normalized_character_sequence_agreement"] == 1.
    assert result["disagreement_windows"] == 0
    assert result["human_reference_verified"] is False


def test_no_opencc_does_not_fake_normalization(monkeypatch):
    monkeypatch.setattr(cc, "_t2s_converter", lambda: None)
    result = cc.compare_transcripts(
        [{"start": 0., "end": 2., "text_src": "你好"}],
        [{"start": 0., "end": 2., "text": "你好"}],
        duration=5.)
    assert result["script_normalization"] == "unavailable_not_normalized"
    assert result["normalized_character_sequence_agreement"] is None
    assert result["raw_character_sequence_agreement"] == 1.


def test_invalid_windows_rejected():
    with pytest.raises(ValueError):
        cc.compare_transcripts([], [], duration=0)
    with pytest.raises(ValueError):
        cc.extract_window([], 5, 3)
