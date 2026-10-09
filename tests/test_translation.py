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
    good = json.dumps({"speakers": [{"id": 0, "role": "r", "tone": "formal",
                                     "relations": [{"audience": "audience",
                                                    "pronoun_i": "em",
                                                    "pronoun_you": "anh",
                                                    "is_default": True}]}],
                       "lines": []})
    t = FakeTranslator(["garbage", good])
    out = t.analyze(segs, spks)
    assert t.calls == 3  # 2 batch attempts + 1 metadata pass (reuses script[-1])
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


def _analyze_json(pairs):
    # pairs: [(role, audience, pi, py), ...] -> 1 default relation per speaker
    # + "lines" per-line audiences (accepted key per ANALYZE_SYSTEM)
    return json.dumps({
        "speakers": [
            {"id": i, "role": r, "tone": "formal",
             "relations": [{"audience": aud, "pronoun_i": pi,
                            "pronoun_you": py, "is_default": True}]}
            for i, (r, aud, pi, py) in enumerate(pairs)],
        "lines": []})


def test_post_rule_interviewee_fallback_to_anh():
    # news program: anchor toi/quy vi + interviewee stuck on toi/ban
    # -> post-rule corrects interviewee pronoun_you to "anh"
    t = FakeTranslator([_analyze_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "bạn")])])
    out = t.analyze(make_segments(2), make_speakers())
    assert out[0].pronoun_you == "quý vị"          # presenter untouched
    assert out[1].pronoun_i == "tôi"
    assert out[1].pronoun_you == "anh"              # post-rule fired


def test_post_rule_no_news_program_no_change():
    # no anchor/quy vi signature -> fallback toi/ban left alone
    t = FakeTranslator([_analyze_json([
        ("friend", "audience", "tớ", "cậu"),
        ("friend", "audience", "tôi", "bạn")])])
    out = t.analyze(make_segments(2), make_speakers())
    assert out[1].pronoun_you == "bạn"


def test_post_rule_presenter_not_rewritten():
    # a second presenter with toi/ban is not an interviewee -> untouched
    t = FakeTranslator([_analyze_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("field reporter", "audience", "tôi", "bạn")])])
    out = t.analyze(make_segments(2), make_speakers())
    assert out[1].pronoun_you == "bạn"


def _analyze_batch_json(pairs):
    # same relations format as _analyze_json (batch tables)
    return _analyze_json(pairs)


def _meta_json():
    return json.dumps({"genre": "news", "style": "formal",
                       "setting": "modern", "tone_notes": "Solemn news."})


def test_analyze_batches_long_transcript():
    # 45 câu, batch_size=20 -> 3 batch + 1 metadata + 1 pass trọng tài = 5 calls
    b = _analyze_batch_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "anh")])
    arb = _arbiter_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "anh")])
    t = FakeTranslator([b, b, b, _meta_json(), arb])
    t.batch_size = 20
    segs = make_segments(45)
    out = t.analyze(segs, make_speakers())
    assert t.calls == 5
    assert out[0].pronoun_you == "quý vị"
    assert out[1].pronoun_you == "anh"


def _arbiter_json(pairs):
    # pairs: [(role, audience, pi, py), ...] (+ note, per ARBITER_SYSTEM)
    return json.dumps({"speakers": [
        {"id": i, "role": r, "tone": "formal",
         "relations": [{"audience": aud, "pronoun_i": pi,
                        "pronoun_you": py, "is_default": True}],
         "note": ""}
        for i, (r, aud, pi, py) in enumerate(pairs)]})


def test_analyze_single_batch_skips_arbiter():
    # <= batch_size câu -> 1 batch + 1 metadata, không cần pass trọng tài
    t = FakeTranslator([_analyze_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "anh")]), _meta_json()])
    out = t.analyze(make_segments(17), make_speakers())
    assert t.calls == 2
    assert out[1].pronoun_you == "anh"


def test_analyze_arbiter_locks_final_table():
    # 45 câu -> 3 batch + 1 metadata + 1 pass trọng tài = 5 calls; trọng tài chốt
    b = _analyze_batch_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "bạn")])
    arb = _arbiter_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "anh")])
    t = FakeTranslator([b, b, b, _meta_json(), arb])
    t.batch_size = 20
    out = t.analyze(make_segments(45), make_speakers())
    assert t.calls == 5
    assert out[0].pronoun_you == "quý vị"
    assert out[1].pronoun_you == "anh"  # trọng tài chốt, không phải bạn


def test_analyze_arbiter_fails_falls_back_to_majority():
    # trọng tài hỏng 3 lần -> gộp đa số dự phòng
    b = _analyze_batch_json([
        ("news anchor", "audience", "tôi", "quý vị"),
        ("interviewee", "0", "tôi", "anh")])
    t = FakeTranslator([b, b, b, _meta_json(), "not json", "{bad", "```oops"])
    t.batch_size = 20
    out = t.analyze(make_segments(45), make_speakers())
    assert t.calls == 7
    assert out[1].pronoun_you == "anh"  # đa số 3/3 batch


def test_analyze_all_batches_fail_keeps_defaults():
    t = FakeTranslator(["not json"] * 9)  # 3 batch x 3 retries
    t.batch_size = 20
    out = t.analyze(make_segments(45), make_speakers())
    assert t.calls == 9
    assert out[0].pronoun_i == "tôi" and out[0].pronoun_you == "bạn"


def _audience_batch_json():
    return json.dumps({
        "speakers": [
            {"id": 0, "role": "reporter", "tone": "formal",
             "relations": [{"audience": "audience", "pronoun_i": "tôi",
                            "pronoun_you": "quý vị", "is_default": True}]},
            {"id": 1, "role": "guest", "tone": "formal",
             "relations": [{"audience": "0", "pronoun_i": "tôi",
                            "pronoun_you": "anh", "is_default": True}]}],
        "lines": [{"id": 0, "audience": "audience"},
                  {"id": 1, "audience": "0"}]})


def test_analyze_fills_line_audience():
    t = FakeTranslator([_audience_batch_json(), _meta_json()])
    segs = make_segments(2)  # idx0: speaker0, idx1: speaker1
    t.analyze(segs, make_speakers())
    assert segs[0].audience == "audience"
    assert segs[1].audience == "0"


def test_analyze_respects_manual_audience():
    # review #1 đặt tay audience -> analyze chỉ điền chỗ còn trống
    t = FakeTranslator([_audience_batch_json(), _meta_json()])
    segs = make_segments(2)
    segs[1].audience = "audience"  # đặt tay trước
    t.analyze(segs, make_speakers())
    assert segs[0].audience == "audience"  # LLM điền
    assert segs[1].audience == "audience"  # giữ nguyên đặt tay


def test_translate_uses_per_audience_pronouns():
    # mỗi câu tra (speaker, audience) -> cặp đại từ đúng trong prompt
    t = FakeTranslator([json.dumps(
        {"translations": [{"id": 0, "text_vi": "VI 0"},
                           {"id": 1, "text_vi": "VI 1"}]})])
    segs = make_segments(2)
    segs[0].audience = "audience"
    segs[1].audience = "0"
    spks = make_speakers()
    spks[0].relations = [
        {"audience": "audience", "pronoun_i": "tôi",
         "pronoun_you": "quý vị", "is_default": True},
        {"audience": "1", "pronoun_i": "tôi",
         "pronoun_you": "cậu", "is_default": False}]
    spks[1].relations = [
        {"audience": "0", "pronoun_i": "tôi",
         "pronoun_you": "anh", "is_default": True}]
    t.translate(segs, spks)
    assert "SPEAKER_0 (to AUDIENCE)" in t.last_user
    assert "SPEAKER_1 (to SPEAKER_0)" in t.last_user
    assert "to 'audience': tôi/quý vị (default)" in t.last_user
    assert "to '0': tôi/anh (default)" in t.last_user


def test_pronoun_hit_word_boundary():
    from translation.base import BaseTranslator
    hit = BaseTranslator._pronoun_hit
    assert hit("thành phố đẹp", "anh") is False   # không khớp nhầm
    assert hit("chào anh nhé", "anh") is True
    assert hit("Cảm nhận của tôi", "tôi") is True
    assert hit("bạn bè các bên", "bạn") is True


def test_flag_missing_pronouns():
    from translation.base import BaseTranslator
    t = FakeTranslator([])
    spks = make_speakers()
    spks[0].pronoun_i, spks[0].pronoun_you = "tôi", "quý vị"

    def segs_with_src(src_texts):
        segs = make_segments(len(src_texts))
        for s, src in zip(segs, src_texts):
            s.text_src = src
            s.text_vi = "Ngày 6 tháng 9, khai mạc hội chợ."  # không đại từ
            s.needs_review = False
        return segs

    # nguồn không có đại từ nhân xưng -> không đánh dấu (tránh nhiễu tin tức)
    segs = segs_with_src(["这是第0句话", "这是第1句话", "这是第2句话",
                          "这是第3句话", "这是第4句话", "这是第5句话"])
    t._flag_missing_pronouns(segs, spks)
    assert not any(s.needs_review for s in segs)

    # nguồn có 我/我们/你 nhưng bản dịch thiếu đại từ đã khóa -> đánh dấu
    # đúng câu (chỉ loa 0 có cặp khóa tôi/quý vị; loa 1 là tôi/bạn -> bỏ qua)
    segs = segs_with_src(["我觉得很好", "这是第1句话", "我们都同意",
                          "这是第3句话", "你觉得呢", "这是第5句话"])
    t._flag_missing_pronouns(segs, spks)
    assert [s.index for s in segs if s.needs_review] == [0, 2, 4]

    # bản dịch có đại từ (kể cả viết hoa đầu câu) -> không đánh dấu
    segs = segs_with_src(["我觉得很好", "我们都同意"])
    segs[0].text_vi = "Tôi thấy rất tốt."
    segs[1].text_vi = "Kính thưa quý vị, chào mừng."
    t._flag_missing_pronouns(segs, spks)
    assert not any(s.needs_review for s in segs)

    # cặp fallback tôi/bạn -> không đánh dấu (không chắc)
    segs = segs_with_src(["我觉得很好", "我们都同意", "你觉得呢"])
    t._flag_missing_pronouns(segs, make_speakers())  # defaults tôi/bạn
    assert not any(s.needs_review for s in segs)


def test_sample_for_metadata_short_sends_all():
    from translation.base import BaseTranslator
    segs = make_segments(50)
    assert BaseTranslator._sample_for_metadata(segs) == segs


def test_sample_for_metadata_even_spread():
    from translation.base import BaseTranslator
    segs = make_segments(200)
    sample = BaseTranslator._sample_for_metadata(segs)
    assert len(sample) == 100  # 10 chunk x 10 câu
    idx = [s.index for s in sample]
    assert idx[0] == 0                    # chunk đầu từ câu 0
    assert idx[-1] >= 190                 # chunk cuối gần hết video
    assert len(set(idx)) == 100           # không trùng


def test_video_metadata_parses_json():
    meta_json = json.dumps({"genre": "news", "style": "formal",
                            "setting": "modern",
                            "tone_notes": "Solemn news tone."})
    t = FakeTranslator([meta_json])
    meta = t.analyze_video_metadata(make_segments(10), make_speakers())
    assert t.calls == 1
    assert meta["genre"] == "news"
    assert meta["tone_notes"] == "Solemn news tone."


def test_video_metadata_defaults_on_bad_json():
    t = FakeTranslator(["not json", "{bad", "```oops"])
    meta = t.analyze_video_metadata(make_segments(10), make_speakers())
    assert t.calls == 3
    assert meta == {"genre": "other", "style": "other", "setting": "other",
                    "tone_notes": ""}


def test_video_context_block_in_translate_system():
    from translation import prompts
    assert prompts.video_context_block(None) == ""
    assert prompts.video_context_block({}) == ""
    sys_txt = prompts.translate_system_with_names(
        None, {"genre": "period drama", "style": "formal",
               "setting": "historical", "tone_notes": "Solemn."})
    assert "VIDEO CONTEXT" in sys_txt
    assert "period drama" in sys_txt
    assert "tại hạ" in sys_txt
    sys_plain = prompts.translate_system_with_names(None, None)
    assert "period drama" not in sys_plain
    assert "\n- Genre:" not in sys_plain  # không nhét metadata khi meta=None


def test_audience_label_value_roundtrip():
    from project.schema import audience_label_vi, audience_value_vi as av
    assert audience_label_vi("audience") == "Khán giả"
    assert audience_label_vi("all") == "Tất cả"
    assert audience_label_vi("1") == "Loa 1"
    assert audience_label_vi("") == "Chưa rõ"
    assert audience_label_vi("xyz") == "Chưa rõ"
    assert av("Khán giả") == "audience"
    assert av("Tất cả") == "all"
    assert av("Loa 2") == "2"
    assert av("Chưa rõ") == ""
    assert av("") == ""
    assert av("Loa x") is None
    assert av("bậy bạ") is None
    # roundtrip
    for v in ("audience", "all", "0", "3", ""):
        assert av(audience_label_vi(v)) == v


def test_translate_user_marks_context_not_to_translate():
    from translation import prompts
    u = prompts.build_translate_user(["SPEAKER_0: ..."], ["[2] X: y"],
                                     None, ["[0] X: a", "[1] X: b"])
    assert "CONTEXT ONLY" in u
    assert "do NOT include their ids" in u
    assert "return exactly these ids" in u
    # không context -> không có section context
    u2 = prompts.build_translate_user(["SPEAKER_0: ..."], ["[2] X: y"])
    assert "CONTEXT ONLY" not in u2
