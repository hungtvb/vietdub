# No-Overwrite Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve existing videos and subtitles when the dubbing pipeline or editor exports to a path that already exists.

**Architecture:** Add shared output-path helpers that select the first unused numbered name and publish completed temporary files without replacing an existing destination. Use them in normal rendering and editor export; persist the actual path returned by the renderer.

**Tech Stack:** Python, `pathlib`, existing FFmpeg subprocess calls, existing editor worker.

**Spec:** [Reliability hardening design](../specs/2026-10-25-reliability-hardening-design.md)

## Global Constraints

- Avoid adding runtime dependencies.
- Do not overwrite an existing user output, even when retrying a render.
- The output rule covers both MP4 and an SRT sidecar when `sub_mode="srt"`.
- Only save the render checkpoint after the MP4 and any required sidecar are complete.
- Keep the editor's numbered naming and apply the same no-replace rule in its export helper.

## Review Focus

- `<stem>_vidub.mp4` already exists — preserve it and use `_2`, then `_3`, etc.
- Only the paired SRT exists — choose a new common base name rather than replace the SRT.
- A destination appears after candidate selection — publication must fail safely and retry with the next candidate.
- FFmpeg fails after starting — remove temporary/partial artifacts and do not save a render checkpoint.
- Editor target or its generated SRT already exists — preserve both and use the next numbered editor output.

---

### Task 1: Add reusable output naming and no-replace publication

**Files:**
- Create: `media/output.py`

**Interfaces:**
- Produces: `next_available_output_path(requested: str | Path, paired_extensions: tuple[str, ...] = ()) -> Path`.
- Produces: `publish_no_replace(temp_path: Path, target_path: Path) -> Path`, raising `FileExistsError` if the target appeared after selection and removing any target it created if publication fails.

- [ ] **Step 1: Implement numbered candidate selection**

  Use the requested path if it and all paired extension paths are free. Otherwise try `_2`, `_3`, etc. before the requested suffix until the full output set is free.

- [ ] **Step 2: Implement no-replace publication**

  Publish a completed temporary artifact without replacing a target that exists. Ensure a failed publication cleans up only the destination created by that call.

- [ ] **Step 3: Manually verify candidate and collision behavior**

  Check an unused target, an existing MP4, an existing paired SRT, and a target created between allocation and publication. Confirm existing bytes remain unchanged.

- [ ] **Step 4: Commit the completed helper**

  ```bash
  git add media/output.py
  git commit -m "feat: add no-overwrite media output helpers"
  ```

### Task 2: Apply no-overwrite publication to pipeline and editor rendering

**Files:**
- Modify: `media/render.py:48-111`
- Modify: `media/editor.py:20-117`
- Modify: `core/orchestrator.py:474-495`

**Interfaces:**
- Consumes: `media.output.next_available_output_path()` and `media.output.publish_no_replace()` from Task 1.
- Produces: both render functions return the actual final `Path`; `_step_render()` saves that actual path and an `srt_out` path when SRT output is enabled.

- [ ] **Step 1: Stage normal render output under a unique temporary name**

  In `media.render.render()`, allocate an unused final MP4 path (including the paired `.srt` in SRT mode), render to a unique same-directory temporary MP4, and publish the completed MP4 and required SRT with no-replace semantics. If a collision occurs during publication, remove only the paired output created by this call, choose the next numbered base, and retry. Return the selected final path. Remove temporary or newly published partial outputs if the render fails.

- [ ] **Step 2: Apply the same rule to edited exports**

  In `media.editor.export_edit()`, preserve the current editor naming base and SRT behavior, but allocate a free target/sidecar pair and publish completed temporary files without replacing either existing file. If a collision occurs during publication, remove only the paired output created by this call, choose the next numbered base, and retry. Return the actual path.

- [ ] **Step 3: Persist the actual pipeline output**

  In `Orchestrator._step_render()`, assign the `Path` returned by `mrender.render()` to `proj.video_out`; save that actual path and, for SRT mode, its output sidecar path as `srt_out` in the render checkpoint.

- [ ] **Step 4: Manually verify the five Review Focus cases**

  Run the normal render and editor export against existing MP4/SRT outputs; cause one render failure; confirm originals remain byte-for-byte unchanged, new output names are numbered, partial files are removed, and checkpoints store the actual path only after success.

- [ ] **Step 5: Commit the completed integration**

  ```bash
  git add media/render.py media/editor.py core/orchestrator.py
  git commit -m "fix: prevent dubbing exports from overwriting outputs"
  ```

**Verification note:** This plan uses manual acceptance checks only; it does not add or run tests.
