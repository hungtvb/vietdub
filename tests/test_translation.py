# Translation base: edge case 7 (bad JSON -> retry 3 -> default pronouns),
# edge case 8 (line count/id mismatch -> retry -> single-line fallback),
# edge case 9 (proper-noun rule in prompt), batching.
import json

import pytest

from tests.conftest import FakeTranslator, make_segments, make_speakers
from translation import prompts
from translation.base import _parse_json, translate_with_fallback


def _good(start, n):
    return json.dumps({"translations": [{"id": start + i, "text_vi": f"VI {start + i}"}
                                        for i in range(n)]})


def test_translate_happy_path():
    segs = make_segments(4)
    t = FakeTranslator([_good(0, 4)])
    out = t.translate(segs, make_speakers())
    assert [s.text_vi for s in out] == [f"VI {i}" for i in range(4)]
    assert t.calls == 1  # single batch


def test_batching_splits_large_input():
    segs = make_segments(45)
    t = FakeTranslator([_good(0, 20), _good(20, 20), _good(40, 5)])
    t.batch_size = 20
    out = t.translate(segs, make_speakers())
    assert t.calls == 3
    assert all(s.text_vi for s in out)


def test_bad_json_retries_then_fallback_pronouns():
    # edge case 7: 3 bad replies -> analyze keeps default toi/ban
    segs = make_segments(2)
    spks = make_speakers()
    t = FakeTranslator(["not json", "{bad", "```oops```"])
    out_spks = t.analyze(segs, spks)
    assert t.calls == 3
    assert out_spks[0].pronoun_i == "tôi"
    assert out_spks[0].pronoun_you == "bạn"


def test_bad_json_recovers_on_retry():
    segs = make_segments(2)
    spks = make_speakers()
    good = json.dumps({"speakers": [{"id": 0, "role": "r",
                                     "speaking_to": "a", "pronoun_i": "em",
                                     "pronoun_you": "anh", "tone": "formal"}]})
    t = FakeTranslator(["garbage", good])
    out = t.analyze(segs, spks)
    assert t.calls == 2
    assert out[0].pronoun_i == "em"


def test_line_mismatch_fallback_single():
    # edge case 8: batch returns fewer lines 3x -> single-line fallback
    segs = make_segments(3)
    short = json.dumps({"translations": [{"id": 0, "text_vi": "VI 0"}]})
    single = lambda i: json.dumps(
        {"translations": [{"id": i, "text_vi": f"LE {i}"}]})
    t = FakeTranslator([short, short, short,
                        single(0), single(1), single(2)])
    out = t.translate(segs, make_speakers())
    assert [s.text_vi for s in out] == ["LE 0", "LE 1", "LE 2"]


def test_proper_noun_rule_in_prompt():
    # edge case 9
    sys_prompt = prompts.translate_system_with_names(["乌兰察布"])
    assert "乌兰察布" in sys_prompt
    assert "proper name" in sys_prompt.lower() or "Proper-name" in sys_prompt
    base_sys = prompts.translate_system_with_names()
    assert "NEVER translate a proper name" in base_sys


def test_parse_json_code_fence():
    d = _parse_json('```json\n{"a": 1}\n```')
    assert d == {"a": 1}
    with pytest.raises(ValueError):
        _parse_json("no json here")


def test_fallback_chain_uses_next_provider():
    # edge case 15 plumbing: first provider raises, second works
    from translation.base import TranslateError
    bad = FakeTranslator([TranslateError("down")])
    good = FakeTranslator([_good(0, 2)])
    segs = make_segments(2)
    out, used = translate_with_fallback([bad, good], segs, make_speakers())
    assert used == "fake"
    assert all(s.text_vi for s in out)


def test_fallback_chain_all_fail():
    from translation.base import TranslateError
    bad = FakeTranslator([TranslateError("down")])
    # google-free disabled here: with it enabled the chain would NOT raise
    with pytest.raises(TranslateError):
        translate_with_fallback([bad], make_segments(1), make_speakers(),
                                use_google_free=False)


def test_skip_analyze_no_second_llm_call():
    # step [5] must NOT re-run analyze when step [4] already did (checkpoint)
    class NoAnalyze(FakeTranslator):
        def analyze(self, segs, spks):
            raise AssertionError("analyze called twice")

    t = NoAnalyze([_good(0, 2)])
    out, used = translate_with_fallback([t], make_segments(2),
                                        make_speakers(), skip_analyze=True)
    assert used == "fake"
    assert all(s.text_vi for s in out)


def test_google_free_last_resort(monkeypatch):
    # all LLM providers down -> google_translate_free is wired in, not dead
    from translation import base as tbase
    from translation.base import TranslateError
    bad = FakeTranslator([TranslateError("down")])
    monkeypatch.setattr(
        tbase, "google_translate_free",
        lambda texts, src="zh-CN", dst="vi":
        [f"GG{i}" for i in range(len(texts))])
    out, used = translate_with_fallback([bad], make_segments(2),
                                        make_speakers())
    assert used == "google_free"
    assert [s.text_vi for s in out] == ["GG0", "GG1"]
