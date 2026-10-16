"""Render approved Vietnamese lines with offline ZeroTTS, no translation fallback."""
import json,os
from pathlib import Path
from core.job import Job
from core.settings import Settings
from core.orchestrator import Orchestrator
from project.schema import Project,Segment,Speaker
from project import io
video=Path("private_input/input.mp4").resolve()
p=Path("translations/approved.json")
assert video.is_file() and p.is_file(),"Missing video or approved translation"
data=json.loads(p.read_text(encoding="utf-8"))
assert data["schema_version"]==1
segments=[Segment.from_dict(x) for x in data["segments"]]
speakers={x["id"]:Speaker.from_dict(x) for x in data["speakers"]}
assert segments and speakers and len({s.index for s in segments})==len(segments)
assert all(s.text_vi.strip() and s.text_src.strip() and s.text_vi.strip()!=s.text_src.strip() and s.end>s.start and s.speaker in speakers for s in segments),"Missing or untranslated lines"
output=Path("output/input_vidub.mp4").resolve()
output.parent.mkdir(exist_ok=True)
job=Job(project=Project(name="stage2",video_source="file",video_in=str(video),video_out=str(output),sub_mode="none",overnight=True,review_stops=False))
settings=Settings(path=Path("output/stage2-settings.json"))
settings.set("tts_provider","zerotts")
settings.set("zerotts_model_dir","model/ZeroTTS")
runner=Orchestrator(job,settings)
for step in ("fetch","extract"): runner._run_step(step)
io.save_segments(job.job_dir,"translate",segments)
io.save_speakers(job.job_dir,"analyze",speakers)
for step in ("tts","mix","render"): runner._run_step(step)
assert output.is_file() and output.stat().st_size>100000
# Validate that the delivered MP4 has NO subtitle stream.
import subprocess
probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(output)], capture_output=True, text=True, check=True)
streams = [s["codec_type"] for s in json.loads(probe.stdout)["streams"]]
assert "video" in streams and "audio" in streams and "subtitle" not in streams
assert not output.with_suffix(".srt").exists()
print("Final dubbed MP4:",output,"lines:",len(segments))
