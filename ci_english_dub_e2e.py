#!/usr/bin/env python3
"""Real English video E2E: faster-whisper -> existing LLM -> Edge-TTS -> MP4.

No fake transcript, synthetic Vietnamese, or automatic human approval.
This lightweight video fixture deliberately lacks verified diarization;
speaker identity is a visible QA limitation, not a claim of correctness.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path
from project.schema import Segment
from translation.llm_e2e import analyze_and_translate, revise_flagged_lines, translation_quality_flags
from translation.quality import review_with_llm, structural_issues
from ci_chinese_dub_e2e import probe, fit_voices, render_clip, make_llm, VI_VOICE
from tts.edge_tts import EdgeTTS


def transcribe_real_english(video, duration, model_name="base"):
    from faster_whisper import WhisperModel
    # Video can have an audio stream with nonzero PTS start. Preserve
    # that delay as silence in WAV, so Whisper timestamps match video time.
    wav=Path(video).parent/"english_whisper_timeline_16k.wav"
    subprocess.run(["ffmpeg","-nostdin","-y","-v","error",
                    "-i",str(video),"-vn","-af",
                    "aresample=async=1:first_pts=0",
                    "-ar","16000","-ac","1",str(wav)],check=True)
    model=WhisperModel(model_name,device="cpu",compute_type="int8")
    raw,details=model.transcribe(str(wav),language="en",beam_size=5,
                                 vad_filter=True)
    rows=list(raw)
    segments=[]
    for item in rows:
        start=max(0.,float(item.start))
        end=min(duration,float(item.end))
        content=(item.text or "").strip()
        if end-start < .12 or not content:
            continue
        segments.append(Segment(
            index=len(segments),start=start,end=end,speaker=0,
            text_src=content,source_lang="en",needs_review=True,
            identity_status="UNVERIFIED"))
    if not segments:
        raise RuntimeError("Whisper transcribed no audible English")
    if any(seg.start<0 or seg.end>duration+.2
           or seg.start>=seg.end for seg in segments):
        raise ValueError("Bad ASR segment timestamps")
    return segments,{"engine":"faster-whisper","model":model_name,
                     "forced_language":"en","reported_language":details.language,
                     "speaker_diarization_verified":False,
                     "segment_count":len(segments)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--video",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--llm-provider",choices=["ollama","9router"],default="ollama")
    parser.add_argument("--llm-model",default="qwen2.5:3b")
    parser.add_argument("--ollama-url",default="http://127.0.0.1:11434")
    parser.add_argument("--whisper-model",default="base")
    args=parser.parse_args()
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    qa={"status":"RUNNING","human_approved":False,
        "translation_quality_pass":False,"asr_accuracy_measured":False,
        "speaker_identity_unverified":True}
    try:
        video=Path(args.video)
        duration,_=probe(video)
        qa["input_seconds"]=duration
        qa["source_sha256"]=hashlib.sha256(video.read_bytes()).hexdigest()
        lines,asr=transcribe_real_english(video,duration,args.whisper_model)
        qa["asr"]=asr
        provider=make_llm(args)
        qa["translation"]=analyze_and_translate(lines,provider)
        first=review_with_llm(lines,provider,
                              video_metadata=qa["translation"]["video_context"])
        qa["initial_llm_semantic_review"]=first
        eligible=set(first["auto_repair_eligible_ids"])
        requested=[item for item in first["issues"] if item["id"] in eligible]
        seen={item["id"] for item in requested}
        basic=structural_issues(lines)
        for seg in lines:
            reasons=basic.get(seg.index,[])
            if seg.index not in seen and ("QUESTION_FORM_LOST" in reasons):
                requested.append({"id":seg.index,"reasons":reasons})
        qa["llm_revision"]=revise_flagged_lines(lines,provider,flagged=requested)
        qa["translation_quality_flags"]=translation_quality_flags(lines)
        qa["final_llm_semantic_review"]=review_with_llm(
            lines,provider,video_metadata=qa["translation"]["video_context"])
        if any("EMPTY_OR_SOURCE_ECHO" in reasons
               for reasons in structural_issues(lines).values()):
            raise ValueError("LLM produced untranslated English")
        qa["question_count_source"]=sum("?" in s.text_src for s in lines)
        qa["question_count_vi"]=sum("?" in s.text_vi for s in lines)
        qa["tts_provider"]="Edge-TTS"
        EdgeTTS(voice_female=VI_VOICE,concurrency=2,retries=2).synthesize(
            lines,out/"tts")
        qa["tts"]=fit_voices(lines,out)
        qa["video"]=render_clip(video,out,lines,duration)
        qa["technical_pass"]=True
        qa["status"]="RENDERED_TECHNICALLY_REVIEW_REQUIRED"
        qa["quality_human_verified"]=False
        (out/"review_lines.json").write_text(json.dumps(
            [s.to_dict() for s in lines],ensure_ascii=False,indent=2),
            encoding="utf-8")
        print("REAL_ENGLISH_WHISPER_LLM_TTS_MP4_OK",len(lines))
    except Exception as exc:
        qa["status"]="FAILED"
        qa["error"]=type(exc).__name__+": "+str(exc)[:500]
        raise
    finally:
        (out/"qa.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2),
                                 encoding="utf-8")


if __name__=="__main__":
    main()
