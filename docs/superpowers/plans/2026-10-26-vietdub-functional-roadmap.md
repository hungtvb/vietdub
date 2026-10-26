# VietDub Functional Upgrade Plan

**Source design:** [Functional upgrade roadmap](../specs/2026-10-26-vietdub-functional-roadmap.md)

**Execution:** phase-by-phase; Phase 1 and Phase 2 are active in separate worktrees.

## Global constraints

- Keep `Orchestrator` responsible for exactly one `Job`.
- Keep batch scheduling outside the orchestrator and process jobs sequentially.
- Never bypass review stops or replace a user's existing export.
- A failed job must retain its checkpoint, status, and useful error text.
- Scope UI changes to the work being implemented; the production UI pass is already merged.
- Verification claims must distinguish static inspection from live model/service/media execution.

## Phase 1 — Existing-feature integrity

1. Guard source transcript merges so incompatible speaker/audience labels cannot be collapsed silently.
2. Preserve edits when the merge is rejected or saving fails.
3. Record the behavior and acceptance rules in a short spec and implementation plan.
4. Review the diff and static checks; no live translation or real-audio claims without evidence.

## Phase 2 — Sequential batch queue

1. Define queue item lifecycle and its relationship to persisted `Job` and `Project` objects.
2. Add a queue view that accepts multiple local videos and shows per-item status/progress.
3. Run one orchestrator at a time and isolate each item's checkpoint/output directory.
4. Hold the queue at review stops; pause/cancel must not silently advance to another item.
5. Decide and document restart behavior. Persist a queue manifest before calling the feature overnight-ready.
6. Review the full flow statically and report any live provider/render behavior not exercised.

## Phase 3 — Job history and restart recovery

1. Discover saved jobs from the per-user data directory without loading malformed entries into the UI.
2. Offer resume only for jobs with valid project/checkpoint state.
3. Revalidate source media and downstream artifacts before resuming.
4. Preserve review states and let the user choose whether to continue or inspect.

## Phase 4 — Synchronized subtitle editing

1. Track edited lines whose current speech no longer matches their displayed subtitle.
2. Offer selective speech regeneration with the existing voice/configuration.
3. Rebuild mixed audio and final render from the updated TTS checkpoint.
4. Keep prior files and clearly mark subtitle-only changes.

## Phase 5 — Release evidence

1. Define repeatable checks for startup, settings, review edits, resume, and export.
2. Exercise real local media and first-use model/service paths where available.
3. Verify packaging on supported operating systems.
4. Publish a short report separating passed checks from unavailable external dependencies.

## Current handoff

- Existing-feature team: implement the bounded Phase 1 transcript-merge integrity fix.
- New-feature team: implement the first coherent Phase 2 batch queue slice or return a concrete blocker and reduced safe scope.
- Integrator: review both branch diffs, resolve overlap, and merge only work that meets its acceptance criteria.
