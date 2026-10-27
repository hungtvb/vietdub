# VietDub Job History and Restart Recovery — Design

**Status:** Approved by user
**Date:** 2026-10-26

## Intent

Let users find past and interrupted dubbing jobs, inspect their state, and
continue safe work after closing or restarting VietDub. Restore an interrupted
batch in its original order while keeping the existing one-job orchestrator
contract.

## Current behavior

- Jobs are stored below the per-user `JOBS_ROOT`; each job has `project.json`,
  stage checkpoints, artifacts, and a run log.
- `Job.to_dict()` and `Job.from_dict()` exist but no app flow persists or loads
  job status through them. `project.json` remains the only project snapshot.
- Checkpoints are written by stage. `core.checkpoint.has_step()` checks both
  checkpoint structure and key artifacts before the orchestrator resumes.
- The batch queue stores its entries and order only in memory. It can stop at
  review, pause, cancellation, or failure, but closing the app loses pending
  queue entries.
- Startup creates the main window directly. It does not discover saved jobs.

## Approaches considered

### A. Persist the batch queue only

Write queue membership and order to one local manifest. This is the smallest
change and restores overnight batches, but single-video jobs and jobs from
older sessions still have no history surface.

### B. Unified job history plus a durable active queue — selected

Give every job a versioned metadata record, show all discoverable jobs in one
history window, and keep a separate manifest for pending batch membership and
order. The history window links to job records; the queue manifest links to job
IDs after a job starts. This supports both single-video recovery and ordered
batch recovery without making the orchestrator batch-aware.

### C. Reconstruct state from project and checkpoint files only

Infer every job state by scanning existing project/checkpoint files. This
avoids adding job metadata, but cannot reliably distinguish interrupted,
cancelled, or failed work, and cannot restore queued videos that have not yet
created a job. It leaves too much state implicit.

## Goals

- Discover valid job directories under the current per-user data directory.
- Show job name, status, last known stage, and updated time in a local history
  view.
- Restore the active batch's membership and order after restart, including
  items that have not started yet.
- Revalidate the project, source availability, checkpoints, and produced
  artifacts before enabling resume.
- Resume paused, failed, cancelled, and interrupted work only after an
  explicit user action.
- Reopen the appropriate human review screen for jobs saved at `REVIEW`; never
  advance the batch past an uncompleted review.
- Keep malformed or unsupported records from breaking startup or hiding other
  valid jobs.
- Continue to run one `Job` at a time through the existing orchestrator.

## Non-goals

- Automatically start or resume work during app startup.
- Add cloud sync, remote queues, concurrent jobs, or model download scheduling.
- Delete job artifacts or add retention/cleanup controls.
- Change translation, ASR, TTS, subtitle, or render behavior.
- Restore the history of queue ordering for batches that already finished; the
  individual jobs remain visible in job history.
- Guarantee recovery when users move or delete source media and required
  checkpoints are unavailable.

## Design

### Per-job record

Add a versioned `job.json` metadata record inside each job directory. Keep the
existing `project.json` as the canonical project/configuration snapshot and
the stage JSON files as the canonical checkpoint data; do not duplicate the
project inside the new record.

The metadata record stores the job ID, schema version, creation/update times,
status, `resume_from`, last reported stage/progress, a lightweight source
identity, and a concise last error when available. For local source files,
record the normalized path, size, and modification time in nanoseconds. For URL
jobs, record the downloaded job-local source artifact after fetch. Do not hash
large videos during discovery. If the recorded source identity changes, do not
silently reuse downstream checkpoints; offer an explicit restart from fetch.

Update the record atomically by writing a temporary file beside the target and
replacing the target, following the existing settings/project write pattern.
Persist state at job creation, run start, each completed stage, and each
terminal or review transition; do not write on every fine-grained progress
signal.

For existing job directories without `job.json`, read a valid `project.json`
and checkpoints as a legacy job. Derive a display state from valid checkpoints
and `stages_done`, and use the project file's modification time as a fallback
timestamp. Do not rewrite legacy records during discovery; write the new
metadata format when the user resumes or otherwise changes that job.

### Active queue manifest

Store one versioned manifest under the per-user VietDub data directory. It
contains the ordered queue entries, local input paths, the active entry, and a
job ID once an entry has created its job. Entries that have no job yet keep a
queue state (`queued`, `done`, or `skipped`). Once a job exists, its `job.json`
is the source of truth for job state; the queue manifest separately records
whether that item was explicitly skipped. This preserves a failed or cancelled
job in history while allowing its batch entry to be skipped. Save the manifest
atomically after add, remove, reorder, start, job creation, skip, stop, and
completion transitions.

Restore an unfinished manifest into the existing queue window. Preserve the
active item and later item order. A queue entry is resolved only when its job
is `DONE` or the user explicitly marks it `SKIPPED`; failed, cancelled, paused,
review, and interrupted jobs remain active and keep the manifest until the user
retries or skips them. Keep completed jobs in job history; clear the active
queue manifest only after every entry is done or explicitly skipped.

If the manifest is malformed or has an unsupported version, preserve it as
diagnostic evidence and show a non-blocking recovery warning. Continue loading
independent job history so one damaged queue cannot prevent app startup.

### Discovery and resume validation

Load the full history lazily when the user opens it. At startup, check only for
an active queue manifest and show a small non-modal recovery notice if one
exists; do not scan every job or read large transcript checkpoints at launch.

Before enabling a resume action:

1. Confirm the job directory is an immediate child of `JOBS_ROOT` and the
   directory ID matches the job record.
2. Parse the job record (or legacy project) with supported schema and known
   status/stage values. Isolate malformed records and explain their state.
3. Load `project.json`, then validate checkpoints and referenced artifacts
   using the existing checkpoint validation behavior.
4. Recompute the safe resume point from the earliest missing or invalid
   checkpoint. Never trust a stored progress percentage as proof an artifact
   exists. When recomputation is possible, show the stage that will rerun and
   the downstream work that will be rebuilt before the user confirms.
5. Confirm that the next required step can access its input. A valid fetched
   video checkpoint may be sufficient even if the original local path moved;
   otherwise the source file must still exist, or a saved URL must be available
   for an explicit refetch.

Jobs persisted as `RUNNING` when the process stopped appear as `Interrupted`.
The user must select **Tiếp tục**. Jobs at `REVIEW` reopen their review window
first. If a required checkpoint is invalid but its inputs are available, offer
to resume from the earliest invalid stage and explain that later stages will be
rebuilt. If an invalid review checkpoint must be regenerated, return to the
configured review stop before proceeding to later steps. Completed jobs open
their output or log and do not offer resume. Missing required inputs remain
visible with a clear blocked reason and a skip/hide-from-active-queue action;
they are not silently marked done.

### History UI

Add a **Lịch sử** entry point to the main window. The history window lists jobs
newest first and shows the source video, state, last stage, and updated time.
Actions are state-aware: continue/retry, reopen review, open output, or open
log. A damaged record remains isolated and does not expose a resume action.

When an active batch manifest exists, show **Khôi phục hàng đợi** in the
history window. It reopens the saved queue without starting it. The user can
inspect the list and explicitly continue the current job or skip a blocked
item. Do not allow a new queue to replace the unfinished manifest; the user
must finish it or explicitly resolve every pending item as skipped first. The
current queue window continues to be the single place that controls queue order
and item actions.

### Failure handling

- A write failure for `job.json` or the active queue manifest must be visible
  to the user. Do not advance the queue or mark an entry resolved when the
  transition could not be persisted.
- A bad job record, bad project file, bad queue manifest, or bad checkpoint
  must not stop discovery of other entries.
- Preserve corrupt metadata with a `.corrupt` suffix when it can be moved
  safely. Never overwrite valid job records while recovering malformed data.
- Keep source and output files untouched during discovery and resume
  validation.

## Constraints

- Keep one `Job` per video and keep queue scheduling outside `Orchestrator`.
- Keep all new state in the existing per-user VietDub data directory.
- Use versioned JSON and atomic replacement for the job and queue manifests.
- Do not automatically bypass manual review, overwrite exports, or start
  provider/model work at launch.
- Preserve compatibility with job directories created before this feature.

## Acceptance criteria

- A batch queued but not started is restored in its original order after
  restart.
- A batch interrupted during an item is restored with that item selected and
  later items still queued.
- An interrupted item is never resumed automatically; the user explicitly
  chooses to continue.
- A job at a review stop reopens its review screen before any later queue item
  starts.
- Resume is disabled with an actionable reason when required project/source
  state is invalid or an invalid checkpoint cannot be rebuilt from available
  inputs; recoverable checkpoint gaps show the stage that will be rerun.
- A missing or malformed job/queue record does not crash startup or prevent
  valid jobs from appearing.
- Legacy jobs with `project.json` and checkpoints appear in history and can be
  resumed only after the same validation rules pass.
- A completed job appears as complete and can open its output without rerunning
  the pipeline.
- Failed/cancelled queue items remain in the restored manifest until the user
  explicitly retries or skips them; skipped jobs remain visible in job history.
- Persisted job and queue records are atomic; a failed save does not silently
  advance batch state.

## Open implementation choices

- The builder can choose the concrete `JobStore`/`QueueStore` module boundaries
  and Qt table layout, following the existing core and UI patterns.
- The builder can choose whether to keep a finished queue manifest as a
  diagnostic archive before clearing the active manifest, provided completed
  jobs remain discoverable and restart never replays them automatically.

## Decisions from independent design review

- A queue item is resolved only by successful completion or explicit skip.
  Failed, cancelled, paused, review, and interrupted jobs keep the active
  manifest. A skipped job remains in history with its original job status.
- An invalid checkpoint does not automatically block recovery. Recompute from
  the earliest invalid stage when its inputs are available, show the rebuild
  scope, and require the user to confirm. If inputs are unavailable, block with
  a reason. If regeneration reaches a configured review stop, reopen that
  review before continuing.
