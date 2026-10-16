"""Real Chinese ASR handoff for review/translation outside CI."""
import json
from pathlib import Path
from core.job import Job
from core.settings import Settings
from core.orchestrator import Orchestrator
from project.schema import Project
from project import io
video=Path("private_input/input.mp4").resolve()
assert video.is_file()
job=Job(project=Project(name="stage1",video_source="file",video_in=str(video),overnight=True,review_stops=False))
runner=Orchestrator(job,Settings(path=Path("output/stage1-settings.json")))
for step in ("fetch","extract","asr","gender"):
    runner._run_step(step)
segments=io.load_segments(job.job_dir,"asr") or []
speakers=io.load_speakers(job.job_dir,"gender") or {}
assert segments and speakers
Path("output").mkdir(exist_ok=True)
Path("output/asr-handoff.json").write_text(json.dumps({"schema_version":1,"segments":[s.to_dict() for s in segments],"speakers":[s.to_dict() for s in speakers.values()]},ensure_ascii=False,indent=2),encoding="utf-8")
print("ASR lines:",len(segments),"speakers:",len(speakers))
