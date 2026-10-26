# Artifact-Aware Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent VietDub from skipping a pipeline step or reporting `DONE` when a checkpoint's required media file is missing or empty.

**Architecture:** Keep JSON shape checks in `core/checkpoint.py` and extend `has_step()` with artifact validation for file-producing stages. Make the orchestrator use that same result for completion, skipping, and resume selection, starting at the earliest invalid step.

**Tech Stack:** Python, `pathlib`, existing JSON checkpoints and `Orchestrator`.

**Spec:** [Reliability hardening design](../specs/2026-10-25-reliability-hardening-design.md)

## Global Constraints

- Keep orchestration independent of Qt.
- Keep the existing job ID and checkpoint format compatible where possible.
- A required artifact must be a regular file with size greater than zero.
- Do not deep-probe media files during resume.

## Review Focus

- `fetch.video_path` was deleted or moved — resume must start at `fetch`.
- `extract.wav_path` is missing or zero bytes — resume must start at `extract`.
- One non-empty TTS `audio_vi` or `tts_meta.dub_track` is missing — resume must start at `tts`.
- `mix.mixed_wav` is missing — resume must start at `mix`.
- `render.video_out` or the required SRT sidecar is missing — resume must start at `render`.

---

### Task 1: Validate checkpoint artifacts and select the earliest invalid stage

**Files:**
- Modify: `core/checkpoint.py:20-98`
- Modify: `core/orchestrator.py:63-115`

**Interfaces:**
- Produces: `has_step(job_dir: Path, step: str, *, sub_mode: str = "") -> bool`; the optional mode preserves existing two-argument callers.
- Produces: `Orchestrator._has_step(step: str) -> bool`, passing the effective render mode from settings with `job.project.sub_mode` as fallback.

- [ ] **Step 1: Add non-empty-file validation**

  Add a private checkpoint helper that returns true only for an existing regular file with size greater than zero. Catch path/permission errors and return false.

- [ ] **Step 2: Validate file-producing checkpoints**

  Keep `_looks_valid()` structure checks. In `has_step()`, additionally validate `fetch.video_path`, `extract.wav_path`, `mix.mixed_wav`, and `render.video_out`. For `tts`, validate each non-empty segment `audio_vi` path and the sibling `tts_meta.json` `dub_track` path. For SRT mode, validate `video_out.with_suffix(".srt")`; prefer the `srt_out` path recorded by new checkpoints when present.

- [ ] **Step 3: Route orchestrator checks through `_has_step()`**

  Use `_has_step()` in the all-complete shortcut, the per-step skip check, and `_first_missing_step()`. Preserve corrupt JSON handling and `invalidate_from()` behavior.

- [ ] **Step 4: Reconcile requested resume with missing earlier artifacts**

  If a caller requests a later step but an earlier step is invalid, start at the earlier invalid step. If the requested step is earlier than the first invalid step, honor the requested step. With no explicit request, retain the earliest-missing behavior.

- [ ] **Step 5: Manually verify the five Review Focus cases**

  For each artifact listed above, remove or truncate it, then resume the job. Confirm that it does not report `DONE`, resumes at the earliest affected step, and invalidates dependent checkpoints.

- [ ] **Step 6: Commit the completed task**

  ```bash
  git add core/checkpoint.py core/orchestrator.py
  git commit -m "fix: validate pipeline artifacts before resume"
  ```

**Verification note:** This plan uses manual acceptance checks only; it does not add or run tests.
