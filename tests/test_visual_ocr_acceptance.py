"""Regression for real-output subtitle QA semantic comparison."""
from media.visual_ocr_acceptance import compare_text


def test_chinese_dialogue_still_legible_is_failed():
    q=compare_text("也是第一个走了 代表通道","也是第一个走了ws 代表通道站")
    assert q["status"]=="failed" and q["similarity"]>=.55


def test_clean_render_without_readable_chinese():
    q=compare_text("这个责任还是比较重大的","")
    assert q["status"]=="no_readable_cjk"


def test_unknown_original_cannot_count_as_clean():
    q=compare_text("0 坟-sa","")
    assert q["status"]=="inconclusive"


def test_unrelated_chinese_must_be_reviewed_not_auto_pass():
    q=compare_text("全国人大代表发言","你好今天天气不错")
    assert q["status"]=="review"
