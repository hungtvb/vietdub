"""Reusable, conservative post-ASR audio coverage audit.

Checks energy in audio spans outside ASR timestamps. Acoustic energy is NOT
proof of speech; this is only a candidate for human review or second ASR.
Do not silently add fabricated transcript/timestamps or mark content approved.
"""
from __future__ import annotations
import math
import numpy as np
import soundfile as sf

def audit_unaligned_audio(wav_path,segments,min_gap_seconds=1.0):
    samples,sr=sf.read(str(wav_path),dtype="float32",always_2d=False)
    if samples.ndim==2:
        samples=np.mean(samples,axis=1)
    duration=len(samples)/float(sr)
    if not segments or duration<=0:
        return {"status":"REVIEW_REQUIRED","reason":"No timed transcript",
                "uncovered":[], "flagged_count":0}
    ordered=sorted(segments,key=lambda s:s.start)
    intervals=[]
    prev=0.0
    for s in ordered:
        if s.start>prev:
            intervals.append((prev,s.start))
        prev=max(prev,s.end)
    if duration>prev:
        intervals.append((prev,duration))
    # 100ms windows estimate relative acoustic floor for this particular file.
    block=max(1,int(sr*.1))
    n=len(samples)//block
    if n==0:
        raise ValueError("Audio too short for coverage analysis")
    frames=samples[:n*block].reshape(n,block)
    rms=np.sqrt(np.mean(frames.astype(np.float64)**2,axis=1))
    floor=float(np.percentile(rms,20))
    threshold=max(.007,2.5*floor)
    uncovered=[]
    for start,end in intervals:
        if end-start<min_gap_seconds:
            continue
        a=max(0,int(start/.1))
        b=min(n,int(math.ceil(end/.1)))
        energy=rms[a:b]
        if energy.size==0:
            continue
        active=float(np.mean(energy>threshold))
        median=float(np.median(energy))
        warning=active>=.35 and median>=threshold*.85
        uncovered.append({
            "start":round(start,3),"end":round(end,3),
            "seconds":round(end-start,3),
            "acoustically_active_fraction":round(active,3),
            "median_rms":round(median,5),
            "possible_missing_speech":bool(warning)})
    flagged=[item for item in uncovered if item["possible_missing_speech"]]
    return {
        "status":("POSSIBLE_ASR_OMISSIONS_REVIEW_REQUIRED" if flagged
                  else "NO_HIGH_ENERGY_GAPS_DETECTED_NOT_HUMAN_VERIFIED"),
        "method":"energy_in_unaligned_audio_not_speech_vad",
        "speech_accuracy_measured":False,
        "covered_until_seconds":round(max(s.end for s in ordered),3),
        "audio_seconds":round(duration,3),
        "coverage_window_count":len(uncovered),
        "flagged_count":len(flagged),
        "uncovered":uncovered}
