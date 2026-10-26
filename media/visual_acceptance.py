"""Decoded-frame QA for actual cleanup exports (safety checks, not image-quality proof).

Checks exact frame count/FPS, unrelated-scene edits, and unexpected jumps
at mask activation/deactivation. Manual required timestamps catch coverage
gaps. The report is intentionally NOT proof of artifact-free inpainting.
"""
from __future__ import annotations

import json
from pathlib import Path


def audit_video(source, output, plan, *, required_subtitle_times=(),
                max_outside_mae=9., max_extra_jump=8.):
    import cv2
    import numpy as np

    original, exported = cv2.VideoCapture(str(source)), cv2.VideoCapture(str(output))
    try:
        if not original.isOpened() or not exported.isOpened():
            raise ValueError("cannot decode source and output")
        fps = float(original.get(cv2.CAP_PROP_FPS))
        new_fps = float(exported.get(cv2.CAP_PROP_FPS))
        if fps <= 0 or abs(fps-new_fps)>.025:
            raise ValueError("FPS differs between source and output")
        width=int(original.get(cv2.CAP_PROP_FRAME_WIDTH))
        height=int(original.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (width,height) != (int(exported.get(cv2.CAP_PROP_FRAME_WIDTH)),
                              int(exported.get(cv2.CAP_PROP_FRAME_HEIGHT))):
            raise ValueError("source/output dimensions differ")
        regions=plan.get("regions",[])
        issues=[]
        for t in required_subtitle_times:
            if not any(r.get("kind")=="subtitle" and
                       float(r["start"])<=t<float(r["end"]) for r in regions):
                issues.append(f"no reviewed subtitle removal at t={t:.2f}s")
        boundaries=[float(r[e]) for r in regions for e in ("start","end")]
        decoded_source=decoded_output=0
        errors=[]
        jumps=[]
        last_a=last_b=None
        while True:
            oka,a=original.read()
            okb,b=exported.read()
            if not (oka and okb):
                if oka:decoded_source+=1
                if okb:decoded_output+=1
                # The shorter stream may end first; count the remaining frames.
                while original.grab(): decoded_source+=1
                while exported.grab(): decoded_output+=1
                break
            i=decoded_source
            decoded_source+=1
            decoded_output+=1
            t=i/fps
            near=any(abs(t-v)<.24 for v in boundaries)
            if near and last_a is not None:
                for r in regions:
                    if min(abs(t-r["start"]),abs(t-r["end"]))>=.24:continue
                    x1,y1,x2,y2=map(int,r["box"])
                    x1,y1=max(0,x1),max(0,y1)
                    x2,y2=min(width,x2),min(height,y2)
                    if x2<=x1 or y2<=y1: continue
                    sub=np.s_[y1:y2,x1:x2]
                    before=float(np.mean(np.abs(a[sub].astype(np.int16)-
                                               last_a[sub].astype(np.int16))))
                    after=float(np.mean(np.abs(b[sub].astype(np.int16)-
                                              last_b[sub].astype(np.int16))))
                    if after-before>max_extra_jump and after>before*2:
                        jumps.append({"at_seconds":round(t,3),
                                      "source_delta":round(before,2),
                                      "output_delta":round(after,2)})
            if i%5==0 or near:
                safe=np.ones((height,width),dtype=bool)
                for r in regions:
                    if not (r["start"]<=t<r["end"]):continue
                    x1,y1,x2,y2=map(int,r["box"])
                    pad=4
                    safe[max(0,y1-pad):min(height,y2+pad),
                         max(0,x1-pad):min(width,x2+pad)]=False
                if safe.any():
                    error=float(np.mean(np.abs(a[safe].astype(np.int16)-
                                               b[safe].astype(np.int16))))
                    errors.append(error)
                    if error>max_outside_mae:
                        issues.append(f"unexpected edit at frame {i}: outside MAE {error:.2f}")
            last_a,last_b=a,b
        if decoded_source != decoded_output:
            issues.append(f"frame loss: source={decoded_source}, output={decoded_output}")
        if jumps:
            issues.append(f"{len(jumps)} unexpected mask-boundary jumps")
        return {
            "source_frames":decoded_source,"output_frames":decoded_output,"fps":fps,
            "outside_samples":len(errors),
            "max_outside_mae":round(max(errors,default=0.),3),
            "boundary_jumps":jumps[:15],
            "required_subtitle_times":list(map(float,required_subtitle_times)),
            "pass_structural_checks":not issues,
            "issues":list(dict.fromkeys(issues)),
            "quality_warning":"Structural checks do not prove invisible subtitles, "
                              "natural reconstruction, or clean logos. Check rendered frames and OCR."
        }
    finally:
        original.release()
        exported.release()


def write_audit(report_path, video, output, plan, *, required_subtitle_times=()):
    result=audit_video(video,output,plan,
                       required_subtitle_times=required_subtitle_times)
    dest=Path(report_path)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result
