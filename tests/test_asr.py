# ASR post_fix (port of recognition/_base.py::_post_fix):
# edge case 4: overlap -> preserve evidence + needs_review; garbage dropped;
# end<=start dropped; index renumbered.
from asr.funasr_adapter import FunASRAdapter
from project.schema import Segment


def _seg(i, start, end, text, spk=0):
    return Segment(index=i, start=start, end=end, speaker=spk, text_src=text)


def test_overlap_is_preserved_and_both_flagged():
    # edge case 4: preserve simultaneous dialogue; never truncate speaker 1.
    segs = [_seg(0, 0.0, 5.0, "câu một", 0),
            _seg(1, 4.0, 8.0, "câu hai", 1)]
    out = FunASRAdapter.post_fix(segs)
    assert len(out) == 2
    assert out[0].end == 5.0
    assert out[1].start == 4.0
    assert out[0].needs_review is True
    assert out[1].needs_review is True


def test_garbage_lines_dropped():
    segs = [_seg(0, 0.0, 2.0, "。。。!!!"),
            _seg(1, 2.0, 4.0, "câu thật"),
            _seg(2, 4.0, 6.0, "   ")]
    out = FunASRAdapter.post_fix(segs)
    assert [s.text_src for s in out] == ["câu thật"]


def test_end_le_start_dropped():
    segs = [_seg(0, 0.0, 2.0, "ok"), _seg(1, 3.0, 3.0, "x"),
            _seg(2, 5.0, 4.0, "y")]
    out = FunASRAdapter.post_fix(segs)
    assert len(out) == 1 and out[0].text_src == "ok"


def test_index_renumbered():
    segs = [_seg(5, 0.0, 2.0, "a"), _seg(9, 2.0, 4.0, "b")]
    out = FunASRAdapter.post_fix(segs)
    assert [s.index for s in out] == [0, 1]


def test_chinese_text_kept():
    segs = [_seg(0, 0.0, 3.0, "乌兰察布的风很大")]
    out = FunASRAdapter.post_fix(segs)
    assert len(out) == 1
