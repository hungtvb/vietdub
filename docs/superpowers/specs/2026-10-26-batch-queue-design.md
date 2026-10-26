# VietDub Sequential Batch Queue — Design

## Intent

Let a user submit several local videos and process them in order without
rebuilding the one-job pipeline. The queue is a new layer above `Orchestrator`;
each item remains an independent `Job` with its own checkpoint and output.

## Goals

- Add multiple local video files, inspect the ordered list, remove or reorder
  pending entries, and start the batch.
- Run at most one job at a time through the existing `ProgressWindow` and
  `Orchestrator` contracts.
- Show a per-video status and overall progress.
- Keep the active item selected through manual review, pause, cancellation, and
  failure. Never silently advance past an item that needs a person or retry.
- Let the user explicitly resume/retry the blocked item or skip it and continue.

## Phase 1 scope

- Same-session queue of local video files.
- Audio track 0 is selected for every item.
- The app reads the current voice, translation, subtitle, output-directory, and
  review settings when it creates each item.
- Each job uses the existing `JOBS_ROOT/<job_id>` checkpoints and rendering
  behavior.
- Queue stops after the current item is paused, cancelled, or failed until the
  user chooses resume/retry or skip.

## Deferred to a later phase

- Persisting and restoring the queue manifest after closing or crashing the app.
- Download URLs in batch, per-file track selection, queue editing while a job
  is running, and scheduling/parallel processing.
- A report file with aggregate batch metrics.

## Architecture

`BatchQueueWindow` owns queue entries and starts one `ProgressWindow` per item.
`ProgressWindow` reports optional progress/result callbacks while preserving its
existing review, pause, retry, cancel, and finish screens. Once an item is
complete and the user leaves its finish screen, the queue starts the next
pending item. A review result is still the same active item; the queue never
interprets `REVIEW` as a completed job.

## Acceptance criteria

- Duplicate local paths are not added twice; missing files are rejected.
- Adding, removing, and reordering work before the queue starts.
- Starting creates a distinct `Job` and project for each file and processes
  them serially.
- The queue shows current stage progress and terminal states for every item.
- `REVIEW` and `PAUSED` hold the queue on the active item. `FAILED` and
  `CANCELLED` require an explicit retry/resume or skip action.
- If a queued file disappears before its job starts, the row is marked failed
  and can only be skipped; retry is disabled until the user re-adds a valid
  file in a new queue.
- Outputs and checkpoints remain owned by their corresponding jobs.
- The UI remains usable at the app's compact supported window size.
