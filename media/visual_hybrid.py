"""Sequence reviewed CV and pretrained LaMa methods without OCR re-analysis.

Both modes are explicitly chosen by the reviewer in one plan. A mode never
silently falls back to blur when a trained model or clean donor is missing.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from media.visual_cleanup import Config, VisualCleanup
from media.visual_lama_cpu import render_lama_cpu

CV_SOURCES={"user","temporal-clean-plate","exemplar-patch","flat-strip-repaint"}
NEURAL_SOURCE="neural-window"


def render_reviewed_hybrid(video, output, plan, *, model_path,
                           ffmpeg="ffmpeg", crf=18, mode="inpaint"):
    source=Path(video).resolve()
    out=Path(output).resolve()
    if not source.is_file() or source==out:
        raise ValueError("Invalid hybrid source/destination")
    if str(source)!=plan.get("source") or plan.get("version")!=1:
        raise ValueError("Hybrid plan source/version does not match input")
    regions=plan.get("regions",[])
    cv_regions=[r for r in regions if r.get("source") in CV_SOURCES]
    neural=[r for r in regions if r.get("source")==NEURAL_SOURCE]
    unknown=[r for r in regions if r.get("source") not in (CV_SOURCES|{NEURAL_SOURCE})]
    if unknown:
        raise ValueError("Plan contains unsupported/automatic region; review it first")
    if not (cv_regions or neural):
        raise ValueError("Hybrid plan contains no approved cleanup regions")
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix="vietdub-hybrid-") as working:
        intermediate=Path(working)/"cv-restored.mp4"
        if cv_regions:
            reviewed={**plan,"regions":cv_regions}
            VisualCleanup(Config(mode=mode,auto_logo=False)).render(
                source,intermediate,reviewed,ffmpeg=ffmpeg)
        else:
            intermediate=source
        if neural:
            return render_lama_cpu(intermediate,out,model_path=model_path,
                                   regions=neural,ffmpeg=ffmpeg)
        # If there is no neural region we can atomically publish the validated
        # CV video. Source remains untouched; no need to reencode again.
        import shutil
        from media.output import publish_no_replace
        with TemporaryDirectory(dir=out.parent,prefix=".hybrid-") as temp:
            copied=Path(temp)/"final.mp4"
            shutil.copy2(intermediate,copied)
            publish_no_replace(copied,out)
        return out
