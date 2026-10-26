# VietDub Functional Upgrade Roadmap

**Date:** 2026-10-26

**Status:** Active scan; Phase 1 work split across existing-feature and new-feature teams.

## Scope

This scan covers the desktop workflow, nine-step orchestrator, persisted job/checkpoint data, ASR and translation providers, Edge-TTS, media render/editor, and the documented overnight workflow. The UI and reliability changes from PR #2 are already merged to `main`.

## Current product shape

- A user selects one local video or downloads one URL, then the app creates one `Job` and runs one `Orchestrator`.
- The pipeline supports per-step checkpoints and per-job logs. `Project` can be loaded from disk, but the app has no job discovery/history flow and no current caller of `load_project()`.
- Subtitle review supports source transcript edits, speaker/audience mapping, split/merge, and translated subtitle edits.
- The editor can change subtitle text/timing and export a new video, but changing text does not regenerate the corresponding dubbed speech; the README already discloses this limitation.
- `DESIGN.md` describes a sequential batch queue as a future capability. The current app does not queue multiple videos.

## Findings ranked by user impact

### P1 — Keep merged transcript metadata accurate

The source-review merge action currently combines adjacent transcript text while retaining the first segment's speaker and audience. Merging lines from different speakers or audiences can silently change who the transcript says spoke and who they addressed. The existing-feature team is implementing a compatibility guard and clear feedback.

### P2 — Keep related review checkpoints in sync

Source review writes the transcript and speaker checkpoints separately; translation review writes translated segments and video metadata separately. If a later write fails, one part may already be on disk. The UI keeps the unsaved screen open, but the on-disk pair is not transactional. Handle this in a later integrity pass with a staged snapshot or rollback strategy.

### P1 — Process multiple videos without parallel-job risk

Batch processing is the largest documented product gap for overnight work. Build a sequential queue that reuses the one-job orchestrator contract, shows per-item status, and respects review, pause, cancel, and failure behavior. Queue restart behavior must be explicit; an overnight mode must not imply recovery unless its queue manifest is durable.

### P1 — Recover an interrupted job after app restart

Checkpoint files and `Project` serialization exist, but the UI does not discover prior jobs or offer resume after a restart. This prevents the documented crash/power-loss recovery flow from being available to users. Plan the job-history/recovery surface after the batch queue's persistence contract is known.

### P2 — Keep edited subtitle text aligned with dubbed audio

Current edits can produce a subtitle that differs from the already synthesized line. Add selective TTS regeneration or an explicit re-dub workflow, preserving the original audio and requiring review before export.

### P2 — Close release-evidence gaps

PR #2 had no GitHub status checks or workflow runs reported by GitHub. The repository has module-level test files and real-audio ASR documentation, but this scan did not run tests. A release phase should define repeatable smoke evidence for first-use model downloads, audio playback, Edge-TTS, export, and Windows packaging.

## Phased delivery

### Phase 1 — Existing workflow data integrity

- Prevent transcript merges that cross speaker or audience boundaries.
- Keep user edits intact when a merge is rejected or persistence fails.
- Review source/translation save and navigation paths for silent loss or stale state.

**Acceptance:** the merge action either preserves correct speaker/audience metadata or explains why it cannot merge; no invalid merge is committed.

### Phase 2 — Sequential local-video batch queue

- Add and remove local files before starting a batch.
- Process jobs one at a time; do not run concurrent ASR/TTS models.
- Show each item's queued/running/review/done/failed/cancelled state and current stage.
- Continue after a failed item only when that behavior is explicit and the failure is preserved for review.
- Respect review stops and user pause/cancel actions.

**Acceptance:** multiple local videos can be queued and processed in order without state crossing between jobs; output paths and checkpoints remain per job.

### Phase 3 — Durable queue and job recovery

- Persist queue membership/order and per-job state under the user data directory.
- On restart, identify interrupted jobs and offer a safe resume path from their earliest invalid checkpoint.
- Preserve review-required states rather than automatically bypassing them.

**Acceptance:** closing/reopening the app does not lose the queue or mark interrupted work complete; each resumed job remains isolated.

### Phase 4 — Subtitle/audio editing consistency

- Let users regenerate speech for changed lines or explicitly mark lines as subtitle-only edits.
- Rebuild downstream mix/render artifacts after regenerated audio.
- Keep prior exports untouched and surface which lines still use stale audio.

**Acceptance:** the exported subtitle and spoken dub match for every line the user marks synchronized.

### Phase 5 — Release readiness and real-media evidence

- Run the project's agreed unit/regression checks and a small, diverse real-video matrix.
- Verify first-use model setup, audio playback, Edge-TTS, render output, restart recovery, and packaged Windows startup.
- Record unavailable external-service checks separately from pass results.

**Acceptance:** a concise release report lists the exact flows exercised, evidence, and remaining platform/service limits.

## Work split for the current phase

- **Existing-feature team:** Phase 1, focused on subtitle/source-review integrity.
- **New-feature team:** Phase 2, focused on a first sequential batch queue slice.
- **Integration review:** reconcile both branches against this roadmap, check scope overlap, and update the roadmap based on what is actually implemented.

## Scan limitations

This is a static source/documentation scan. It does not claim that model downloads, live translation providers, Edge-TTS, full media rendering, or Windows packaging were exercised in this turn.
