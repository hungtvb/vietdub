"""Reconstruct handoff from real Whisper ASR and human-written Vietnamese dub lines.

Outputs a REVIEW DRAFT, not an approved track: mixed speakers/time slots must be checked.
"""
import base64
import gzip
import json
from pathlib import Path

source_path = Path("prior_asr/asr-handoff.json")
payload_path = Path("translations/review_payload.gz.b64")
assert source_path.is_file(), "Real Whisper JSON is missing"
assert payload_path.is_file(), "Vietnamese reviewed lines are missing"
source = json.loads(source_path.read_text(encoding="utf-8"))
assert source["source"].startswith("real_whisper_"), "Require real Whisper ASR"
original = source["segments"]

roles = {
  0: ("Maddie", "female", "maichi"),
  1: ("Ethan", "male", "giahuy"),
  2: ("Cade", "male", "tiendat"),
  3: ("Chloe", "female", "hamy"),
  4: ("Maddie's father", "male", "huuduc"),
  5: ("Cade's father", "male", "quangminh"),
  6: ("Event host", "male", "quangminh"),
  7: ("Cade's friend", "male", "quangminh"),
  8: ("Maddie's mother", "female", "kimoanh"),
  9: ("Unidentified supporting role", "male", "huuduc"),
}

def assemble():
    encoded = payload_path.read_text(encoding="ascii").strip()
    rows = gzip.decompress(base64.b64decode(encoded, validate=True)).decode("utf-8").splitlines()
    final = []
    used_ids = []
    for row in rows:
        ids, spk, review, vi = row.split("|", 3)
        src_ids = [int(x) for x in ids.split(",")]
        sid = int(spk)
        assert src_ids and sid in roles and review in ("0","1") and vi.strip()
        assert src_ids == list(range(src_ids[0], src_ids[-1]+1)), "Merge IDs must be consecutive"
        src = dict(original[src_ids[0]])
        src["index"] = len(final)
        src["end"] = original[src_ids[-1]]["end"]
        src["speaker"] = sid
        src["gender"] = roles[sid][1]
        src["text_src"] = " ".join(original[i]["text_src"] for i in src_ids)
        src["text_vi"] = vi
        src["audio_vi"] = ""
        src["needs_review"] = bool(int(review))
        src["audience"] = ""
        assert src["end"] > src["start"], src_ids
        used_ids.extend(src_ids)
        final.append(src)

    assert sorted(used_ids) == list(range(len(original))), "Cannot drop/duplicate any real ASR segment"
    assert len(final) == 241, "Unexpected Vietnamese translation line count"
    assert all(x["text_vi"] and x["text_vi"] != x["text_src"] for x in final)
    speakers = []
    for sid,(role,gender,voice) in roles.items():
        speakers.append(dict(id=sid,gender=gender,confidence=0.5,median_hz=0.,role=role,
                             speaking_to="",pronoun_i="tôi",pronoun_you="cậu" if sid<4 else "bạn",
                             tone="natural Vietnamese film dialogue",relations=[]))
    info = dict(
        genre="modern teen romance, social drama, wealthy families",
        central_story="Maddie rejects Cade's cruel kiss wager and grows close to Ethan; class tensions, rumors, charity boxing and competing fathers complicate their relationship",
        translation_approach="Vietnamese colloquial film dubbing; preserve Maddie/Ethan/Cade/Chloe names; relational pronouns",
        source_asr=source["source"],
        source_segments=len(original),translated_segments=len(final),
        qa_status="REVIEW_REQUIRED",
        review_count=sum(x["needs_review"] for x in final),
        warning="Multiple Whisper utterances join speakers. Role assignments are provisional; do not mark approved without audio/visual verification."
    )
    result=dict(schema_version=1,segments=final,speakers=speakers,video_metadata=info)
    out=Path("translations/review-draft.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("VIETDUB_REAL_TRANSLATION:",len(final),"lines, review:",info["review_count"])
    return out

if __name__=="__main__":
    assemble()
