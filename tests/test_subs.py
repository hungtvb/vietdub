# SRT write/read roundtrip. Burn path tested in test_render.py (edge 11).
from media import subs as msubs
from project.schema import Segment


def test_write_read_roundtrip(tmp_path):
    segs = [Segment(index=0, start=1.5, end=4.25, speaker=0,
                    text_src="你好", text_vi="Chào bạn"),
            Segment(index=1, start=5.0, end=7.0, speaker=1,
                    text_src="再见", text_vi="Tạm biệt")]
    p = msubs.write_srt(segs, tmp_path / "a.srt")
    text = p.read_text(encoding="utf-8")
    assert "00:00:01,500 --> 00:00:04,250" in text
    assert "Chào bạn" in text
    back = msubs.read_srt(p)
    assert len(back) == 2
    assert back[0].text_vi == "Chào bạn"
    assert back[1].start == 5.0


def test_falls_back_to_src(tmp_path):
    segs = [Segment(index=0, start=0.0, end=1.0, speaker=0, text_src="原文")]
    p = msubs.write_srt(segs, tmp_path / "vd_subs_fallback.srt")
    assert "原文" in p.read_text(encoding="utf-8")


def test_special_chars_survive(tmp_path):
    # edge case 11 support: quotes, %, backslash preserved byte-exact
    tricky = "Anh nói: 'giảm 50%' \\ xong."
    segs = [Segment(index=0, start=0.0, end=2.0, speaker=0, text_vi=tricky)]
    p = msubs.write_srt(segs, tmp_path / "t.srt")
    back = msubs.read_srt(p)
    assert back[0].text_vi == tricky
