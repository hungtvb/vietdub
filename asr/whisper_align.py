# VietDub - local WhisperX acoustic alignment shared by CI and desktop app.
"""Align words acoustically without assuming WhisperX preserves segment count."""
from collections import defaultdict
import re


def _overlap(a, b, x, y):
    return max(0.0, min(b, y) - max(a, x))


def associate_aligned_words(items, aligned_segments):
    """Return one list per input utterance even when the aligner drops or splits items."""
    words = []
    for part in aligned_segments:
        for w in (part.get("words") or []):
            a, b = w.get("start"), w.get("end")
            if a is None or b is None or float(b) <= float(a):
                continue
            words.append({"start": float(a), "end": float(b), "word": w.get("word", "")})
    assigned = [[] for _ in items]
    for w in words:
        scores = [_overlap(float(x["start"]), float(x["end"]), w["start"], w["end"])
                  for x in items]
        if not scores:
            continue
        k = max(range(len(scores)), key=scores.__getitem__)
        if scores[k] >= min(.03, (w["end"] - w["start"]) * .25):
            assigned[k].append(w)
    return [sorted(words, key=lambda w: (w["start"], w["end"])) for words in assigned]


def forced_align(raw, wav, *, batch_size=20, device="cpu"):
    """Acoustic alignment; report every fallback. Model-dependent imports are lazy."""
    import whisperx

    audio = whisperx.load_audio(str(wav))
    output = [dict(part, alignment_status="whisper_words_unaligned") for part in raw]
    stats = {"method": "whisperx_forced_alignment", "aligned": 0,
             "fallback_to_whisper_words": 0, "errors": {}}
    groups = defaultdict(list)
    for i, part in enumerate(raw):
        lang = "zh" if re.search(r"[\u3400-\u9fff]", part["text"]) else "en"
        groups[lang].append((i, part))
    for lang, parts in groups.items():
        try:
            model, metadata = whisperx.load_align_model(language_code=lang, device=device)
        except Exception as exc:
            stats["errors"][lang] = f"{type(exc).__name__}: {str(exc)[:280]}"
            stats["fallback_to_whisper_words"] += len(parts)
            continue
        for start in range(0, len(parts), batch_size):
            batch = parts[start:start + batch_size]
            items = [{"start": float(p["start"]), "end": float(p["end"]),
                      "text": p["text"]} for _, p in batch]
            try:
                aligned = whisperx.align(items, model, metadata, audio, device,
                                         return_char_alignments=False)["segments"]
                mapped = associate_aligned_words(items, aligned)
            except Exception as exc:
                stats["errors"][f"{lang}:{start}"] = f"{type(exc).__name__}: {str(exc)[:280]}"
                stats["fallback_to_whisper_words"] += len(batch)
                continue
            for (original_idx, _), words in zip(batch, mapped):
                if words:
                    output[original_idx]["words"] = words
                    output[original_idx]["alignment_status"] = "whisperx_aligned"
                    stats["aligned"] += 1
                else:
                    stats["fallback_to_whisper_words"] += 1
        del model
    if stats["aligned"] + stats["fallback_to_whisper_words"] != len(raw):
        raise RuntimeError("WhisperX alignment accounting mismatch")
    return output, stats
