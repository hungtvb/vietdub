"""Real ZeroTTS smoke test on lines from the actual Whisper+Vietnamese translation."""
import json
from pathlib import Path
import soundfile as sf
from project.schema import Segment
from tts.zerotts_local import ZeroTTSLocal
d=json.loads(Path("translations/review-draft.json").read_text(encoding="utf-8"))
by_speaker={}
for line in d["segments"]:
    sid=line["speaker"]
    if sid not in by_speaker and line["end"]-line["start"]>1.0 and len(line["text_vi"])>12:
        by_speaker[sid]=Segment.from_dict(line)
assert all(s in by_speaker for s in (0,1,2)), "Missing real female/male/antagonist lines"
voices={"0":"maichi","1":"giahuy","2":"tiendat"}
samples=[by_speaker[s] for s in (0,1,2)]
engine=ZeroTTSLocal(model_dir="model/ZeroTTS",voices=voices,local_only=True)
engine.synthesize(samples,Path("output/tts-smoke"))
for s in samples:
    info=sf.info(s.audio_vi)
    assert info.samplerate==44100 and info.duration>.3
    print("REAL ZeroTTS",s.speaker,round(info.duration,2),"sec:",s.text_vi)
