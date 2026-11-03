"""Render an operator-reviewed visual cleanup plan without rerunning OCR.

Usage:
    python -m media.visual_cleanup_review \
      --video /path/input.mp4 \
      --plan /path/reviewed-plan.json \
      --out /path/restored.mp4

The output is video-only; original audio may be remuxed by VietDub final render.
"""
import argparse
import json
from pathlib import Path

from media.visual_cleanup import Config, VisualCleanup, VisualCleanupError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--mode", choices=("blur", "inpaint"), default="blur")
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if str(args.video.resolve()) != plan.get("source"):
        raise VisualCleanupError("The review plan belongs to another source video")
    if not any(r.get("source") in ("temporal-clean-plate", "exemplar-patch", "flat-strip-repaint")
               for r in plan.get("regions", [])):
        raise VisualCleanupError("Plan lacks operator-reviewed clean-plate regions")
    output = VisualCleanup(Config(mode=args.mode,auto_logo=False)).render(
        args.video,args.out,plan,ffmpeg=args.ffmpeg)
    from media.visual_acceptance import write_audit
    report = write_audit(str(output)+".audit.json",args.video,output,plan,
                         required_subtitle_times=plan.get("required_subtitle_times",[]))
    if not report["pass_structural_checks"]:
        raise VisualCleanupError("Output verification failed: "+"; ".join(report["issues"]))
    if plan.get("ocr_qa_samples"):
        from media.visual_ocr_acceptance import audit_rendered_captions
        qa = audit_rendered_captions(
            args.video, output, plan["ocr_qa_samples"],
            lang=plan.get("ocr_qa_lang","chi_sim+eng"))
        from pathlib import Path
        Path(str(output)+".ocr_qa.json").write_text(
            json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8")
        if qa["verdict"] != "no_readable_cjk":
            raise VisualCleanupError(
                "Output OCR quality gate not accepted: "+qa["verdict"]+
                " (see .ocr_qa.json). Review actual frames.")
    print(output)
    print("QA:",str(output)+".audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
