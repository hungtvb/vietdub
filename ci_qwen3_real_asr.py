#!/usr/bin/env python3
"""Run actual local Qwen3-ASR + ForcedAligner on a real clip.

Emits source transcript/timestamps and evidence, never synthetic segments.
No translation, no human approval claim. LLM dubbing runs on another runner.
"""
import argparse
import hashlib
import json
import resource
from pathlib import Path
from asr.qwen3_adapter import Qwen3ASRAdapter
from ci_chinese_dub_e2e import probe
from media.subs import write_srt


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--video",required=True)
    p.add_argument("--wav",required=True,help="Actual mono PCM WAV for official Qwen audio decoder")
    p.add_argument("--out",required=True)
    p.add_argument("--model",default="Qwen/Qwen3-ASR-0.6B")
    p.add_argument("--aligner",default="Qwen/Qwen3-ForcedAligner-0.6B")
    p.add_argument("--device",choices=("auto","cpu","cuda"),default="cpu")
    p.add_argument("--language",default="zh")
    args=p.parse_args()
    target=Path(args.out)
    target.mkdir(parents=True,exist_ok=True)
    path=Path(args.video)
    info={"status":"RUNNING","method":"REAL_LOCAL_QWEN_ASR_FORCED_ALIGN",
          "human_approved":False,"asr_accuracy_verified":False,
          "speaker_identity_verified":False,
          "model":args.model,"aligner":args.aligner}
    try:
        duration,streams=probe(path)
        info["source_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
        info["source_seconds"]=round(duration,3)
        info["source_streams"]=sorted(streams)
        runner=Qwen3ASRAdapter(model=args.model,aligner=args.aligner,
                               device=args.device,language=args.language)
        segments=runner.transcribe(args.wav)
        if any(s.index!=i for i,s in enumerate(segments)):
            raise ValueError("Non-contiguous source indices")
        if any(not (0<=s.start<s.end<=duration+.1) for s in segments):
            raise ValueError("Timestamp invalid or outside clip")
        if not any(s.text_src.strip() for s in segments):
            raise ValueError("Empty Qwen-ASR output")
        from asr.coverage import audit_unaligned_audio
        info["audio_coverage_review"]=audit_unaligned_audio(args.wav,segments)
        info["segments"]=len(segments)
        info["transcript"]="".join(s.text_src for s in segments)
        info["qa"]=runner.last_evidence
        info["peak_rss_kb"]=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        (target/"segments.json").write_text(
            json.dumps([s.to_dict() for s in segments],
                       ensure_ascii=False,indent=2),encoding="utf-8")
        write_srt(segments,target/"qwen_chinese_source.srt",field="text_src")
        info["status"]="QWEN3_ASR_REAL_TIMESTAMPS_PASS_UNAPPROVED"
        print("REAL_QWEN3_ASR_TIMESTAMPS_OK",len(segments),
              "segments, secs",duration,flush=True)
    except Exception as exc:
        if "runner" in locals():
            info["qa"]=runner.last_evidence
        info["status"]="FAILED"
        info["error"]=type(exc).__name__+": "+str(exc)[:500]
        raise
    finally:
        (target/"qa.json").write_text(
            json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
