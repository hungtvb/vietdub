"""Mandarin E2E integrity plus cross-topic translation QA tests."""
import hashlib
import json
import pytest
from project.schema import Segment
from ci_chinese_dub_e2e import tempo_filter,verify_source
from translation.llm_e2e import analyze_and_translate,revise_flagged_lines,translation_quality_flags
from translation.quality import structural_issues,review_with_llm,REVIEW_SYSTEM


def test_speed_filter():
    assert tempo_filter(1.25)=="atempo=1.250000"
    assert tempo_filter(4.5)=="atempo=2.0,atempo=2.0,atempo=1.125000"
    with pytest.raises(ValueError):
        tempo_filter(-1)


def test_source_video_sha256_is_required(tmp_path):
    path=tmp_path/"sample.webm"
    path.write_bytes(b"video A")
    report={"status":"CHINESE_FUNASR_REAL_ASR_COMPLETE",
        "model_backend":"automodel","qa":{"qa_status":"UNAPPROVED"},
        "source_video_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "segment_count":1,"real_transcript":[
            Segment(index=0,start=0,end=2,speaker=0,text_src="大家好").to_dict()]}
    assert verify_source(report,path,3)[0].needs_review
    path.write_bytes(b"video B")
    with pytest.raises(ValueError,match="SHA256"):
        verify_source(report,path,3)


def test_group_preserves_source_ids_and_speakers():
    from asr.dub_grouping import group_for_vietnamese_dub
    pieces=[Segment(index=0,start=0,end=1,speaker=0,text_src="你"),
            Segment(index=1,start=1,end=2,speaker=0,text_src="好。"),
            Segment(index=2,start=2.2,end=3.2,speaker=1,text_src="谢谢。")]
    groups,mapping=group_for_vietnamese_dub(pieces)
    assert [m["original_asr_ids"] for m in mapping]==[[0,1],[2]]
    assert groups[0].text_src=="你好。"


class ContextReviewer:
    name="stub"
    model="stub-reviewer"
    def __init__(self, flagged):
        self.flagged=flagged
        self.inputs=[]
    def _chat(self,system,user):
        assert system==REVIEW_SYSTEM
        request=json.loads(user)
        self.inputs.append(request)
        rows=[]
        for item in request["review_these"]:
            message=self.flagged.get(item["id"])
            rows.append({"id":item["id"],"issues":(
              [{"category":"fact_mismatch","detail":message}] if message else [])})
        return json.dumps({"reviews":rows},ensure_ascii=False)


@pytest.mark.parametrize("source,draft,issue",[
    ("请在十月十日之前付款","Thanh toán trước ngày 20 tháng Mười.",
     "Incorrect payment deadline"),
    ("这药不适合儿童","Thuốc này phù hợp với trẻ em.",
     "Negation was dropped"),
    ("The contract lasts six months","Hợp đồng kéo dài sáu năm.",
     "Six months incorrectly rendered as six years"),
    ("私は来週帰ります","Tôi sẽ trở về vào tháng sau.",
     "Next week was mistranslated as next month"),
])
def test_cross_domain_llm_review_is_generic(source,draft,issue):
    seg=Segment(index=0,start=1,end=4,speaker=0,text_src=source,
                text_vi=draft)
    reviewer=ContextReviewer({0:issue})
    report=review_with_llm([seg],reviewer)
    assert report["flagged_lines"]==1
    assert seg.needs_review is True
    assert report["human_approved"] is False
    assert "亚洲杯" not in REVIEW_SYSTEM
    assert "football" not in REVIEW_SYSTEM.lower()


def test_generic_reviewer_preserves_exact_ids_and_batch_context():
    segs=[Segment(index=i,start=i*3,end=i*3+2,speaker=0,
                  text_src=f"Source {i}",text_vi=f"Bản dịch {i}")
          for i in range(5)]
    p=ContextReviewer({3:"Mismatch"})
    q=review_with_llm(segs,p,batch_size=2)
    assert q["reviewed_lines"]==5
    assert q["llm_calls"]==3
    assert q["flagged_lines"]==1
    assert p.inputs[1]["context_only"][0]["id"]==0
    assert segs[3].needs_review


def test_review_bad_json_fails_closed():
    class Invalid:
        model="bad"
        name="test"
        def _chat(self,system,user):
            return '{"reviews":[{"id":999,"issues":[]}]}'
    seg=Segment(index=0,start=0,end=2,speaker=0,text_src="Hello",
                text_vi="Xin chào")
    q=review_with_llm([seg],Invalid())
    assert q["flagged_lines"]==1
    assert q["issues"][0]["issues"][0]["category"]=="REVIEW_UNAVAILABLE"


def test_generic_revision_has_no_hardcoded_sports_terms():
    class Revision:
        def _chat(self,system,user):
            obj=json.loads(user)
            assert "Asian Cup" not in system
            assert "Asian Cup" not in user
            return json.dumps({"id":obj["requested_id"],
                               "text_vi":"Hợp đồng có hiệu lực trong sáu tháng."},
                              ensure_ascii=False)
    seg=Segment(index=0,start=0,end=4,speaker=0,
                source_lang="en",text_src="The contract lasts six months.",
                text_vi="Hợp đồng kéo dài sáu năm.")
    review={"id":0,"issues":[{"category":"number","detail":"Six months not six years"}]}
    result=revise_flagged_lines([seg],Revision(),flagged=[review])
    assert result["llm_revision_calls"]==1
    assert result["method"]=="contextual_per_line_revision"
    assert len(result["revised"])==1
    assert "sáu tháng" in seg.text_vi
    assert result["human_approved"] is False


def test_structural_qa_does_not_enforce_topic_specific_terms():
    segs=[Segment(index=0,start=0,end=2,speaker=0,source_lang="zh",
                   text_src="中国女足",text_vi="Đội bóng đá nữ Việt Nam")]
    # Basic check cannot establish semantic accuracy. LLM/human review needed.
    assert structural_issues(segs)=={}
    assert translation_quality_flags(segs)["is_ground_truth_score"] is False
    segs[0].text_vi="中国女足"
    assert "SOURCE_SCRIPT_REMAINS" in structural_issues(segs)[0]


def test_default_existing_llm_analysis_and_translation_calls():
    from translation.base import BaseTranslator
    from translation import prompts
    class Fake(BaseTranslator):
        name="fake"
        model="mock"
        def _chat(self,sys,user):
            if sys == prompts.ANALYZE_SYSTEM:
                return json.dumps({"speakers":[{"id":0,"role":"customer",
                 "relations":[{"audience":"audience","pronoun_i":"tôi",
                               "pronoun_you":"quý vị","is_default":True}]}],
                               "lines":[{"id":0,"audience":"audience"}]})
            if sys == prompts.VIDEO_META_SYSTEM:
                return json.dumps({"genre":"other","style":"formal"})
            if sys.startswith(prompts.TRANSLATE_SYSTEM):
                return json.dumps({"translations":[{"id":0,"text_vi":"Xin chào."}]})
            raise AssertionError("Unexpected prompt")
    seg=[Segment(index=0,start=0,end=2,speaker=0,text_src="你好",source_lang="zh")]
    result=analyze_and_translate(seg,Fake())
    assert result["llm_call_counts"]["analyze"]>=1
    assert result["llm_call_counts"]["translate"]>=1
    assert seg[0].text_vi=="Xin chào."
