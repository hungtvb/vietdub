#!/usr/bin/env python3
# VietDub Wave 1 integration test: steps [1]->[5] on the real 55s clip.
# NOT collected by pytest (needs models + network). Run manually:
#   .venv/bin/python tests/integration_wave1.py
#
# Checks:
#  - [2] ASR speaker labels 0->1->0 match
#    pyvideotrans-demo/hidden_files/test_funasr_spk/funasr_paraformer_vad_campp_55s.json
#  - [3] gender of the 2 speakers
#  - [4]+[5] 9Router/mimo-v2.6-flash-free analysis + translation, pronoun check
# Logs per-step time + peak RAM to hidden_files/wave1_integration.log
# (used for the 90-minute extrapolation in Wave 3).
#
# Tony's overnight rule: a step that cannot run unattended is SKIPPED
# (logged), never blocks the rest.
import json
import logging
try:
    import resource
except ImportError:  # Windows has no resource module
    resource = None
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

AUDIO = Path.home() / "workspace/pyvideotrans-demo/work/man_clip/audio.wav"
REF_JSON = (Path.home() / "workspace/pyvideotrans-demo/hidden_files"
            / "test_funasr_spk/funasr_paraformer_vad_campp_55s.json")
LOG_PATH = ROOT / "hidden_files" / "wave1_integration.log"
JOB_DIR = ROOT / "hidden_files" / "wave1_job"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("integration")


def peak_ram_mb() -> float:
    if resource is None:
        return 0.0
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def timed(label, fn):
    t0, ram0 = time.time(), peak_ram_mb()
    try:
        out = fn()
        ok = True
        note = ""
    except Exception as e:  # noqa: BLE001 - logged, step skipped
        out, ok, note = None, False, f"SKIPPED: {e}"
        log.warning("[%s] %s", label, note)
    dt = time.time() - t0
    ram1 = peak_ram_mb()
    line = (f"[{label}] {'OK' if ok else 'FAIL'} time={dt:.1f}s "
            f"ram_start={ram0:.0f}MB ram_peak={ram1:.0f}MB {note}")
    log.info(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return out


def main():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    (JOB_DIR / "stages").mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n=== integration run {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    from core.settings import Settings
    settings = Settings()

    # [1] extract: clip is already 16k mono wav -> verify/convert fast
    def step_extract():
        from media import extract as mextract
        return mextract.extract_audio(AUDIO, JOB_DIR / "stages" / "audio.wav")
    wav = timed("1.extract", step_extract)

    # [2] ASR + speaker labels
    def step_asr():
        from asr.funasr_adapter import FunASRAdapter
        ad = FunASRAdapter(asr_model=settings.get("asr_model"),
                           vad_model=settings.get("vad_model"),
                           punc_model=settings.get("punc_model"),
                           spk_model=settings.get("spk_model"))
        segs = ad.transcribe(str(wav))
        (JOB_DIR / "stages" / "asr.json").write_text(
            json.dumps({"segments": [s.to_dict() for s in segs]},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        return segs
    segments = timed("2.asr", step_asr)

    if segments:
        # compare speaker sequence 0->1->0 vs reference
        ref = json.loads(REF_JSON.read_text(encoding="utf-8"))
        ref_items = ref.get("segments", ref if isinstance(ref, list) else [])
        def norm_spk(s):
            v = s.get("spk", s.get("speaker", 0))
            try:
                return int(str(v).replace("spk", ""))
            except ValueError:
                return 0
        ref_spks = [norm_spk(s) for s in ref_items]
        got_spks = [s.speaker for s in segments]
        # collapse consecutive duplicates for sequence comparison
        def collapse(xs):
            return [x for i, x in enumerate(xs) if i == 0 or x != xs[i - 1]]
        line = (f"[2.asr.check] segments={len(segments)} "
                f"speakers_seq={collapse(got_spks)} ref_seq={collapse(ref_spks)} "
                f"n_speakers={len(set(got_spks))}")
        log.info(line)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # [3] gender
    def step_gender():
        from speaker import gender as mgender
        spks = mgender.estimate_genders(str(wav), segments)
        for seg in segments:
            if seg.speaker in spks:
                seg.gender = spks[seg.speaker].gender
        return spks
    speakers = timed("3.gender", step_gender) if segments else None
    if speakers:
        for sid, sp in speakers.items():
            line = (f"[3.gender.check] speaker {sid}: {sp.gender} "
                    f"(median {sp.median_hz} Hz, conf {sp.confidence})")
            log.info(line)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    # [4]+[5] 9Router/mimo analysis + translation
    def step_translate():
        from translation.nine_router import NineRouterTranslator
        tr = NineRouterTranslator(
            api_key=settings.get("nine_router_key", ""),
            base_url=settings.get("nine_router_url"),
            model=settings.get("nine_router_model"),
            temperature=float(settings.get("llm_temperature", 0.2)),
            batch_size=int(settings.get("translate_batch", 20)))
        spks = tr.analyze(segments, speakers or {})
        segs = tr.translate(segments, spks)
        (JOB_DIR / "stages" / "translate.json").write_text(
            json.dumps({"segments": [s.to_dict() for s in segs]},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        return spks, segs
    result = timed("4+5.translate", step_translate) if segments else None
    if result:
        spks, segs = result
        for sid, sp in sorted(spks.items()):
            line = (f"[4.analyze.check] speaker {sid}: role={sp.role} "
                    f"speaking_to={sp.speaking_to} "
                    f"pronoun_i={sp.pronoun_i} pronoun_you={sp.pronoun_you}")
            log.info(line)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        # pronoun check: reporter (spk 0) -> toi/quy vi; Mr Ly (spk 1) -> toi/anh
        vi_text = " ".join(s.text_vi for s in segs)
        for sid, want_i, want_you in ((0, "tôi", "quý vị"), (1, "tôi", "anh")):
            mine = [s.text_vi for s in segs if s.speaker == sid]
            hit_i = sum(1 for t in mine if want_i in t)
            hit_y = sum(1 for t in mine if want_you in t)
            line = (f"[5.translate.check] speaker {sid}: {len(mine)} câu, "
                    f"'{want_i}' x{hit_i}, '{want_you}' x{hit_y}")
            log.info(line)
            with LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        line = f"[5.translate.sample] {' | '.join(s.text_vi for s in segs[:3])}"
        log.info(line)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    log.info("integration done, log at %s", LOG_PATH)


if __name__ == "__main__":
    main()
