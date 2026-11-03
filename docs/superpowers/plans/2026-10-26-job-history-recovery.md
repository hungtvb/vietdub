> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# VietDub Job History and Restart Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist job state and the active batch queue so users can safely find, inspect, and explicitly resume work after restarting VietDub.

**Architecture:** Keep versioned job metadata beside each existing `project.json`, and store one versioned active queue manifest in the current per-user data directory. Add a non-executing recovery inspector that validates records, inputs, checkpoints, and artifacts before the history and queue windows offer actions; keep execution in the existing one-job `Orchestrator` flow.

**Tech Stack:** Python, `pathlib`, standard-library JSON and dataclasses, PySide6, existing project and checkpoint persistence.

**Spec:** [Job history and restart recovery design](../specs/2026-10-26-job-history-recovery-design.md)

## Global Constraints

- Keep one `Job` per video and keep queue scheduling outside `Orchestrator`.
- Keep all new state in the existing per-user VietDub data directory.
- Use versioned JSON and atomic replacement for the job and queue manifests.
- Do not automatically bypass manual review, overwrite exports, or start provider/model work at launch.
- Preserve compatibility with job directories created before this feature.
- Do not delete job artifacts or modify source/output media during discovery and resume validation.
- Do not add or run automated tests unless requested; use the manual acceptance checks below and syntax/diff checks during implementation.

## File Map

- Create `core/json_io.py` for atomic JSON writes; Task 3 adds the shared safe corrupt-file quarantine helper.
- Create `core/job_store.py` for the versioned `job.json` schema and job metadata persistence.
- Create `core/queue_store.py` for the single active queue manifest and its atomic persistence.
- Create `core/job_recovery.py` for legacy discovery, checkpoint/source validation, and safe resume decisions.
- Create `ui/job_history.py` for the lazy, state-aware history window.
- Modify `core/orchestrator.py` to persist coarse job lifecycle and stage transitions.
- Modify `core/job.py`, `media/fetch.py`, and `core/orchestrator.py` to support an explicitly confirmed URL refetch when its downloaded source identity changes.
- Modify `ui/main_window.py` to expose history, startup queue recovery notice, and job resume/review/output actions.
- Modify `ui/batch_queue.py` to restore and persist the ordered active queue.
- `ui/progress.py` may only change if needed to reopen a saved review state through its existing `show_current_review()` flow; keep its current one-job window contract.

## Interfaces

- `core.json_io.atomic_write_json(path: Path, payload: dict) -> None` writes a temporary sibling and atomically replaces `path`; filesystem errors propagate to the caller.
- `core.json_io.quarantine_file(path: Path) -> Path` makes a temporary sibling copy and atomically links it to `<path>.corrupt` without replacing an existing file or symlink. The original remains intact. A collision raises `FileExistsError`; temporary cleanup errors must not mask the record-validation error.
- `core.job_store.JobRecord` has `schema_version`, `job_id`, `created_at`, `updated_at`, `status`, `resume_from`, `last_stage`, `progress`, `source_identity`, and `last_error` fields. Timestamps are UTC ISO 8601 strings. Local identity is `{kind: "file", path, size_bytes, mtime_ns}`; an unfetched URL starts as `{kind: "url", url}` and is replaced by the downloaded job-local file identity after fetch. `core.job_store.JobStore(root: Path = JOBS_ROOT)` exposes `save(job: Job, *, last_stage: str | None = None, progress: float | None = None, last_error: str | None = None, refresh_source_identity: bool = False) -> JobRecord`, `load(job_id: str) -> JobRecord`, and `record_path(job_id: str) -> Path`.
- `core.queue_store.QueueItemRecord` has stable `entry_id`, local `path`, queue resolution `state` (`queued`, `done`, or `skipped`), and optional `job_id`. `QueueManifest` has `schema_version`, ordered `entries`, and optional `active_entry_id`. In JSON, optional `job_id` and `active_entry_id` keys may be absent or `null`; loading normalizes either form to `None`. `QueueStore(path: Path = ACTIVE_QUEUE_PATH)` exposes `load() -> QueueManifest | None`, `save(manifest: QueueManifest) -> None`, and `clear() -> None`.
- `core.job_recovery.JobInspection` exposes `job_id`, `project: Project | None`, `source_label`, `display_status`, `last_stage`, `updated_at`, `output_path`, `run_log_path`, `resume_from`, `rebuild_steps: list[str]`, `source_changed`, `blocked_reason`, `legacy`, and `damaged` fields. `discover_jobs(store: JobStore, *, sub_mode: str | None = None) -> list[JobInspection]` and `inspect_job(store: JobStore, job_id: str, *, sub_mode: str | None = None) -> JobInspection` validate one job without starting it; `sub_mode` is the app's effective render mode, falling back to `project.sub_mode` and then `burn`.
- A queue item is resolved only when its linked job status is `DONE` or its manifest state is `skipped`. The manifest may persist `done` after the job record is saved; if that queue write fails, the current queue must stop and show the error, then reconcile the already-saved `DONE` job without rerunning it after restart.

## Review Focus

- A corrupt or unsupported `job.json` or queue manifest cannot hide other history or block app startup; tasks 4 and 7 manually confirm isolation and the warning behavior.
- A legacy job with a valid `project.json` and checkpoints appears without a new `job.json` being written during discovery; task 4 manually confirms this.
- A changed or missing source does not silently reuse downstream checkpoints; a valid fetched-video checkpoint remains usable; task 4 manually checks both paths.
- A missing/corrupt checkpoint selects the earliest invalid step, shows the downstream rebuild scope, and returns to the configured review stop; task 4 manually confirms it.
- A changed downloaded URL source is force-refetched only after explicit confirmation, and a failed refresh preserves the prior source artifact; tasks 5–7 manually confirm it.
- Restarted queues preserve active and later item order, keep failures/reviews unresolved, and require an explicit continue or skip; task 6 manually confirms it, including changed URL confirmation and refresh.

---

### Task 1: Add atomic JSON persistence and job metadata records

**Files:**
- Create: `core/json_io.py`
- Create: `core/job_store.py`

**Interfaces:**
- Produces: `atomic_write_json()` and `JobStore`/`JobRecord` as defined above.
- `job.json` is metadata only; `project.json` remains the canonical project snapshot and stage JSON files remain canonical checkpoints.

- [x] **Step 1: Implement `atomic_write_json(path, payload)`** using UTF-8 JSON, a temporary sibling file, and `Path.replace()`; propagate write/replace errors and clean up only the temporary file.
- [x] **Step 2: Implement `JobRecord` version 1** with the exact fields in the Interfaces section; validate supported status values, pipeline step names, finite `progress` from 0 through 100, and a job ID matching `^[A-Za-z0-9_-]{1,64}$` that resolves to one immediate child under the supplied jobs root.
- [x] **Step 3: Implement `JobStore.save()` and `load()`** so first save captures source identity, later saves preserve it unless `refresh_source_identity=True`, `created_at` stays fixed, and `updated_at` changes. Reject malformed or unsupported records without overwriting them. Accept persisted states `idle`, `running`, `paused`, `review`, `done`, `failed`, and `cancelled`; `Interrupted` is display-only. Accept `resume_from`/`last_stage` only when they are known pipeline steps or `None`.
- [x] **Step 4: Add safe quarantine for malformed metadata** using a `.corrupt` sibling only when that target does not already exist; never replace a valid record.
- [x] **Step 5: Manually verify** a round trip, atomic replacement, unsupported-version rejection, malformed-record preservation, and path traversal rejection.
- [x] **Step 6: Run `python -m py_compile core/json_io.py core/job_store.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** `core/json_io.py` and `core/job_store.py`.

  ```bash
  git add core/json_io.py core/job_store.py
  git commit -m "feat: persist job metadata"
  ```

### Task 2: Persist job lifecycle and source identity

**Files:**
- Modify: `core/orchestrator.py`
- Modify: `core/job_store.py` at source identity path normalization.
- Modify: `ui/main_window.py` at `_configure_job()` so new single and batch jobs receive an initial `IDLE` record after `project.json` is saved.
- Modify: `ui/progress.py` only if required to display a persistence failure returned by the orchestrator.

**Interfaces:**
- Consumes: `JobStore.save(job, last_stage=None, progress=None, last_error=None)`.
- Produces: each job has durable metadata at creation, run start, completed stage boundaries, and review/paused/cancelled/failed/done transitions. Progress is coarse stage progress only, never every signal.

- [x] **Step 1: Persist `IDLE` metadata after `_configure_job()` saves `project.json`; if the metadata write fails, show the storage error and do not start that job.**
- [x] **Step 2: Persist `RUNNING` before `Orchestrator.run()` starts provider work, and persist the completed stage plus progress after each stage checkpoint is written.**
- [x] **Step 3: Persist each terminal/review transition and `last_error`; on a metadata write failure, return a visible failed result and do not report `DONE` to the queue.**
- [x] **Step 4: Normalize source identity paths to canonical absolute paths in `core/job_store.py`. Record local file size and `mtime_ns`; after URL fetch call `JobStore.save(..., refresh_source_identity=True)` to record the downloaded job-local file. Do not hash media.**
- [x] **Step 5: Manually verify** job creation, successful completion, review, pause/cancel, failure, and a forced metadata write failure; confirm provider work is not launched when the initial record cannot be saved.
- [x] **Step 6: Run `python -m py_compile core/orchestrator.py ui/main_window.py ui/progress.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** the lifecycle changes.

  ```bash
  git add core/job_store.py core/orchestrator.py ui/main_window.py ui/progress.py
  git commit -m "feat: persist job lifecycle state"
  ```

### Task 3: Persist one ordered active queue manifest

**Files:**
- Create: `core/queue_store.py`
- Modify: `core/json_io.py` to add the shared `quarantine_file(path)` helper.
- Modify: `core/job_store.py` to use that helper and preserve `JobRecordError` when quarantine itself fails.

**Interfaces:**
- Consumes: `atomic_write_json()` and `quarantine_file()` from `core.json_io.py`.
- Produces: `QueueItemRecord`, `QueueManifest`, and `QueueStore` as defined above.
- Use one manifest at `user_data_dir() / "active_queue.json"`; each item has a stable ID so the active item survives edits and restart.

- [x] **Step 1: Implement version 1 manifest parsing and validation**; generate entry IDs with `uuid.uuid4().hex`, store paths as `os.path.normcase(str(Path(path).expanduser().resolve()))`, and validate unique entry IDs/normalized paths, allowed queue resolution states, optional safe job IDs, and an active entry that belongs to the manifest. Accept absent or `null` `job_id`/`active_entry_id` keys and normalize them to `None`.
- [x] **Step 2: Implement `save()` with atomic replacement** and surface filesystem errors; implement `clear()` without deleting or changing job data.
- [x] **Step 3: Implement `quarantine_file(path)` as a temporary sibling copy plus exclusive hard link to `<path>.corrupt`; preserve the source, treat existing files and symlinks as occupied, and ensure temp cleanup errors do not mask the original failure. Refactor `JobStore` to use this helper without allowing quarantine failures to mask a malformed-record error.**
- [x] **Step 4: Preserve invalid manifests as `.corrupt` evidence** without overwriting an existing quarantine file, and expose a typed error that includes the recovery path and reason.
- [x] **Step 5: Manually verify** add/remove/reorder serialization, active-entry round trip, absent and `null` optional keys, malformed/version errors, occupied quarantine path, failed save propagation, and all-done/all-skipped manifest clearing.
- [x] **Step 6: Run `python -m py_compile core/json_io.py core/job_store.py core/queue_store.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** the queue-store and shared quarantine changes.

  ```bash
  git add core/json_io.py core/job_store.py core/queue_store.py
  git commit -m "feat: persist active batch queue"
  ```

### Task 4: Discover history and compute safe recovery decisions

**Files:**
- Create: `core/job_recovery.py`
- Modify: `core/checkpoint.py` only if a non-mutating validation helper is needed; preserve existing artifact checks and corrupt-file evidence behavior.

**Interfaces:**
- Produces: `JobInspection`, `discover_jobs(store)`, and `inspect_job(store, job_id)` as defined above.
- Derive `Interrupted` for persisted `RUNNING` records in the inspection view; do not persist `Interrupted` as a running pipeline state.

- [x] **Step 1: Discover only immediate job-directory children**; require directory ID and metadata ID to match and isolate invalid directories from valid results.
- [x] **Step 2: Load `project.json` and validate metadata/status/stage values; classify missing `job.json` as legacy and derive display status without writing metadata during discovery: all valid checkpoints → `done`; a valid review-stop checkpoint after `asr` or `translate` → `review`; other partial legacy work → `interrupted`; no valid steps → `idle`. Show malformed project/metadata or ID mismatch as `damaged` and non-resumable. Persisted `running` displays as `interrupted`.**
- [x] **Step 3: Validate checkpoints/artifacts in pipeline order using the supplied `sub_mode` (fall back to `project.sub_mode`, then `burn`); compute `resume_from` as the earliest missing/invalid step and `rebuild_steps` as that step through render.**
- [x] **Step 4: Check required next-step inputs and source identity. If the original path is missing but a valid fetched-video artifact exists, permit recovery from that artifact. If the original file exists but its recorded identity changed, set `source_changed=True`, `resume_from="fetch"`, and `rebuild_steps=STEPS` so the UI can require restart-from-fetch confirmation. Otherwise require a readable local source or saved URL; block when required inputs are unavailable.**
- [x] **Step 5: Manually verify** legacy read-only discovery, malformed metadata isolation, path/ID mismatch, source changed/missing cases, valid fetched artifact, earliest invalid step, and invalid review checkpoint return-to-review behavior.
- [x] **Step 6: Run `python -m py_compile core/job_recovery.py core/checkpoint.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** the recovery inspector changes.

  ```bash
  git add core/job_recovery.py core/checkpoint.py
  git commit -m "feat: validate resumable jobs"
  ```

### Task 5: Force-refresh a changed URL source after confirmation

**Files:**
- Modify: `core/job.py`
- Modify: `media/fetch.py`
- Modify: `core/orchestrator.py`

**Interfaces:**
- `Job.force_fetch: bool = False` is transient and is not included in `Job.to_dict()`/`from_dict()` persistence.
- `media.fetch.resolve(source: str, job_dir: str | Path, progress_cb=None, *, force_download: bool = False) -> Path` keeps current behavior when false. For URL jobs with `force_download=True`, download to a unique sibling temporary path with an `.mp4` suffix and atomically replace `source.mp4` only after a successful download; on failure preserve the existing source artifact.
- `Orchestrator._step_fetch()` passes `job.force_fetch` as `force_download` and clears the flag only after a successful fetch. Local-file sources continue to resolve directly.

- [x] **Step 1: Add the transient `force_fetch` Job flag** without adding it to serialized job/project data.
- [x] **Step 2: Extend URL resolution with an opt-in forced download** to a unique sibling temporary MP4 followed by `Path.replace()` on success; clean up the temp on failure without altering an existing `source.mp4`.
- [x] **Step 3: Pass the flag through `_step_fetch()`** and clear it after a successful resolution; keep the normal cache-reuse path unchanged when the flag is false.
- [x] **Step 4: Manually verify** normal URL cache reuse, confirmed forced refresh replacing the source only after success, failed refresh preserving the previous source, local-file behavior, and transient serialization.
- [x] **Step 5: Run `python -m py_compile core/job.py media/fetch.py core/orchestrator.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 6: Commit** the confirmed URL refresh capability.

  ```bash
  git add core/job.py media/fetch.py core/orchestrator.py
  git commit -m "feat: refresh changed URL source on confirmation"
  ```

### Task 6: Restore and persist the active batch queue

**Files:**
- Modify: `ui/batch_queue.py`
- Modify: `ui/main_window.py` queue opening only to pass a restored manifest into the existing queue window.

**Interfaces:**
- Consumes: `QueueStore`, `QueueManifest`, `QueueItemRecord`, and `JobStore` from Tasks 1–3, `inspect_job(..., sub_mode=...)`/`JobInspection` from Task 4, and the transient confirmed `Job.force_fetch` behavior from Task 5.
- Produces: a restored queue keeps its saved order and selected active item; opening it never starts work automatically.

- [x] **Step 1: Load an existing manifest when `BatchQueueWindow` opens** and rebuild rows from manifest entries plus each linked job's `JobInspection`; do not scan the entire job history here.
- [x] **Step 2: Persist add/remove/reorder, queue start, active entry, job creation, stop, skip, and completion transitions. Save the active entry and new job ID before launching `ProgressWindow`; if a save fails, restore the prior in-memory resolution state, show the error, and do not advance or launch the next item.**
- [x] **Step 3: Persist job completion and explicit skip as queue resolution; keep failed, cancelled, paused, review, and interrupted entries unresolved. Preserve completed/skipped history and clear the manifest only when all entries are resolved. If the job record saved `DONE` but the queue save failed, restore that completed job as resolved without rerunning it, then require an explicit user action before processing later items.**
- [x] **Step 4: Restore the blocked active job with state-aware actions; `REVIEW` reopens only when its checkpoint is valid, interrupted/failed/paused jobs require an explicit continue, changed sources require rebuild confirmation and set `force_fetch=True` for URL jobs, and missing-input jobs remain selected until explicitly skipped. Lock add/remove/reorder while restoring an unfinished queue.**
- [x] **Step 5: Manually verify** an unstarted queue restart, crash during the active item, ordering after a completed current item, review reopening, changed URL confirmation and refresh, failed/cancelled retry or skip, missing source, and queue-manifest write failure.
- [x] **Step 6: Run `python -m py_compile ui/batch_queue.py ui/main_window.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** the queue restoration changes.

  ```bash
  git add ui/batch_queue.py ui/main_window.py
  git commit -m "feat: restore interrupted batch queues"
  ```

### Task 7: Add history UI and startup recovery entry points

**Files:**
- Create: `ui/job_history.py`
- Modify: `ui/main_window.py`
- Modify: `ui/progress.py` only if needed for the existing `show_current_review()` route.

**Interfaces:**
- Consumes: `discover_jobs(..., sub_mode=...)`, `inspect_job(..., sub_mode=...)`, `JobStore`, `QueueStore`, the Task 5 `Job.force_fetch` behavior, and the existing `ProgressWindow` callbacks.
- Produces: main-window **Lịch sử** action, non-modal active-queue notice, lazy newest-first history, explicit per-job actions, and **Khôi phục hàng đợi** that only opens the queue window.

- [x] **Step 1: Build a responsive `JobHistoryDialog`** listing source, state, last stage, and update time newest first; show a blocked reason and disable resume for damaged or unavailable jobs.
- [x] **Step 2: Wire state-aware actions:** continue/retry only after safe validation and rebuild confirmation; changed source requires explicit restart-from-fetch confirmation and sets `force_fetch=True` for URL jobs; valid `REVIEW` opens its review window; `DONE` opens output or log; queue restore reopens the saved queue without starting it.
- [x] **Step 3: Add the main-window history entry and a small non-modal recovery notice** based only on the active queue manifest at startup; do not enumerate jobs, load checkpoints, or start provider/model work at app launch.
- [x] **Step 4: Show queue corruption/recovery warnings without blocking startup or hiding valid job history; keep queue item skip/reorder controls in the queue window.**
- [x] **Step 5: Manually verify** first launch without a manifest, active and malformed manifest notices, lazy history discovery, newest-first order, each state-aware action, resizing, and review return flow.
- [x] **Step 6: Run `python -m py_compile ui/job_history.py ui/main_window.py ui/progress.py` and `git diff --check`; expect exit code 0 and no diff-check output.**
- [x] **Step 7: Commit** the history UI changes.

  ```bash
  git add ui/job_history.py ui/main_window.py ui/progress.py
  git commit -m "feat: add job history and recovery actions"
  ```

## Final Acceptance

- [x] Walk through every acceptance criterion in the approved spec using disposable local jobs and queue entries; do not use provider/model work for startup checks.
- [x] Confirm no legacy job is rewritten by opening history, no source/output file is changed during discovery, and no unfinished queue is replaced by a new queue.
- [x] Review `git diff --check`, run syntax compilation for changed Python modules, and inspect the complete diff. Automated tests and video runs remain out of scope unless requested.
