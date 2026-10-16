#!/usr/bin/env python3
"""Run VietDub's real nine-stage pipeline headlessly, with no mock providers."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.job import DONE, Job
from core.orchestrator import Orchestrator
from core.settings import Settings
from project.schema import Project


def main() -> int:
    parser = argparse.ArgumentParser(description="VietDub real end-to-end CLI")
    parser.add_argument("--input", required=True, help="Video file path")
    parser.add_argument("--output", required=True, help="Output .mp4 file path")
    parser.add_argument("--provider", choices=("9router", "ollama"), default="9router")
    parser.add_argument("--ollama-model", default="")
    parser.add_argument("--sub-mode", choices=("srt", "burn"), default="srt")
    parser.add_argument("--settings", default="", help="Optional JSON settings file")
    args = parser.parse_args()

    inp, output = Path(args.input).expanduser().resolve(), Path(args.output).expanduser().resolve()
    if not inp.is_file():
        parser.error(f"Video does not exist: {inp}")
    output.parent.mkdir(parents=True, exist_ok=True)
    settings = Settings(path=Path(args.settings) if args.settings else output.parent / "vietdub-settings.json")
    settings.set("sub_mode", args.sub_mode)
    settings.set("review_stops", False)
    settings.set("overnight", True)
    key = os.environ.get("VIETDUB_9ROUTER_KEY", "").strip()
    if key:
        settings.set("nine_router_key", key)
    if args.ollama_model:
        settings.set("ollama_model", args.ollama_model)
    project = Project(name=inp.stem, video_source="file", video_in=str(inp),
                      video_out=str(output), sub_mode=args.sub_mode,
                      translate_provider=args.provider, overnight=True,
                      review_stops=False)
    job = Job(project=project)
    orchestrator = Orchestrator(job, settings)
    status = orchestrator.run()
    detail = {
        "status": status, "error": orchestrator.last_error,
        "timings_sec": orchestrator.timings,
        "job_id": job.job_id, "job_dir": str(job.job_dir),
        "video_output": str(output) if status == DONE and output.is_file() else None,
    }
    (output.parent / "vietdub-result.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(detail, ensure_ascii=False, indent=2), flush=True)
    return 0 if status == DONE and output.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
