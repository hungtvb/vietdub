"""Real-output OCR acceptance for burned Chinese dialogue (optional Tesseract).

This checks the OUTPUT, not the detector's input OCR boxes. A passing sample
does not prove artifact-free reconstruction; failure means readable source
subtitles remain. Inconclusive OCR is reported, not silently treated as PASS.
Requires locally installed Tesseract chi_sim language pack and pytesseract.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re


def _cjk(text):
    return "".join(re.findall(r"[\u3400-\u9fff]", text or ""))


def compare_text(original, cleaned, *, min_chars=4, retain_ratio=.55):
    src,dst = _cjk(original),_cjk(cleaned)
    if len(src)<min_chars:
        return {"status":"inconclusive","reason":"source OCR too weak",
                "source_text":src,"output_text":dst,"similarity":None}
    matches=SequenceMatcher(a=src,b=dst,autojunk=False)
    common=sum(block.size for block in matches.get_matching_blocks())
    retention=common/max(1,len(src))
    # A very short residual (e.g. punctuation/noise) is not strong proof that
    # original dialogue is still readable, but visual inspection still needed.
    status="failed" if len(dst)>=min_chars and retention>=retain_ratio else (
        "review" if len(dst)>=min_chars else "no_readable_cjk")
    return {"status":status,"source_text":src,"output_text":dst,
            "similarity":round(retention,3),"output_char_count":len(dst)}


def audit_rendered_captions(source, output, samples, *, lang="chi_sim+eng",
                            psm=6, min_chars=4):
    """samples: [{'at': seconds, 'box': [x1,y1,x2,y2]}].

    Fail if original caption survives. Exit in INCONCLUSIVE / REVIEW state
    when OCR is not confident. The list MUST cover representative visible
    caption changes, shot boundaries and onset/offset; no coverage inference.
    """
    import cv2
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Install pytesseract/Tesseract OCR for output quality QA") from exc
    caps=[cv2.VideoCapture(str(source)),cv2.VideoCapture(str(output))]
    if not all(cap.isOpened() for cap in caps):
        for cap in caps:cap.release()
        raise ValueError("Cannot decode OCR QA source and output")
    details=[]
    try:
        for sample in samples:
            sec=float(sample["at"])
            x1,y1,x2,y2=map(int,sample["box"])
            pair=[]
            for cap in caps:
                cap.set(cv2.CAP_PROP_POS_MSEC,sec*1000)
                ok,frame=cap.read()
                if not ok: raise ValueError(f"Missing frame for OCR QA: t={sec}")
                h,w=frame.shape[:2]
                if not (0<=x1<x2<=w and 0<=y1<y2<=h):
                    raise ValueError("OCR QA region exceeds video")
                crop=frame[y1:y2,x1:x2]
                pair.append(pytesseract.image_to_string(
                    crop,lang=lang,config=f"--psm {int(psm)}"))
            result=compare_text(pair[0],pair[1],min_chars=min_chars)
            details.append({"at":sec,"box":[x1,y1,x2,y2],**result})
    finally:
        for cap in caps:cap.release()
    verdict = "failed" if any(x["status"]=="failed" for x in details) else (
        "review" if any(x["status"] in ("review","inconclusive") for x in details)
        else "no_readable_cjk")
    return {"verdict":verdict,"samples":details,
            "quality_warning":"OCR disappearance is not proof of natural background "
                              "or watermark-free output. Human review is mandatory."}
