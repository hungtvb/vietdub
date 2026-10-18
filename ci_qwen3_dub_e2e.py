#!/usr/bin/env python3
"""Dub real Qwen3-ASR timed transcript with existing VietDub LLM/TTS stack."""
import argparse
import json
from pathlib import Path
from project.schema import Segment
from translation.llm_e2e import analyze_and_translate,revise_flagged_lines
from translation.quality import review_with_llm,structural_issues
from ci_chinese_dub_e2e import make_llm,probe,fit_voices,render_clip,VI_VOICE
from tts.edge_tts import EdgeTTS

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--transcript",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--llm-provider",choices=["ollama","9router"],default="ollama")
    p.add_argument("--llm-model",default="qwen2.5:3b")
    p.add_argument("--ollama-url",default="http://127.0.0.1:11434")
    a=p.parse_args()
    out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)
    qa={"status":"RUNNING","human_approved":False,
        "speaker_identity_verified":False,"asr_accuracy_verified":False,
        "quality_human_verified":False}
    try:
        duration,_=probe(a.source)
        src=json.loads(Path(a.transcript).read_text(encoding="utf-8"))
        segs=[Segment.from_dict(row) for row in src]
        if not segs or any(s.index!=i or not (0<=s.start<s.end<=duration+.15)
                           for i,s in enumerate(segs)):
            raise ValueError("Qwen ASR input invalid")
        provider=make_llm(a)
        qa["asr_engine"]="qwen3_asr"
        qa["timed_source_lines"]=len(segs)
        qa["translation"]=analyze_and_translate(segs,provider)
        initial=review_with_llm(segs,provider,
                   video_metadata=qa["translation"]["video_context"])
        qa["initial_review"]=initial
        repair_ids=set(initial["auto_repair_eligible_ids"])
        repair=[row for row in initial["issues"] if row["id"] in repair_ids]
        qa["revision"]=revise_flagged_lines(segs,provider,flagged=repair)
        qa["final_review"]=review_with_llm(segs,provider,
                   video_metadata=qa["translation"]["video_context"])
        issues=structural_issues(segs)
        if any("EMPTY_OR_SOURCE_ECHO" in x for x in issues.values()):
            raise RuntimeError("LLM left untranslated source text")
        EdgeTTS(voice_female=VI_VOICE,concurrency=2,retries=2).synthesize(
            segs,out/"tts")
        qa["tts"]=fit_voices(segs,out)
        qa["video"]=render_clip(a.source,out,segs,duration)
        qa["status"]="RENDERED_TECHNICALLY_REVIEW_REQUIRED"
        qa["technical_pass"]=True
        (out/"review_lines.json").write_text(json.dumps(
            [s.to_dict() for s in segs],ensure_ascii=False,indent=2),
            encoding="utf-8")
        print("QWEN3_ASR_LLM_VI_EDGETTS_MP4_OK",len(segs),flush=True)
    except Exception as exc:
        qa["status"]="FAILED"
        qa["error"]=type(exc).__name__+": "+str(exc)[:500]
        raise
    finally:
        (out/"qa.json").write_text(json.dumps(
            qa,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
