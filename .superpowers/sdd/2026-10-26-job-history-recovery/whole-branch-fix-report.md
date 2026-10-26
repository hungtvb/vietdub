# Whole-branch fix wave report

## Findings addressed

1. **Pending ASR review lost after Back / close**
   - Added a durable `stages/review.json` intent that is separate from the earliest missing pipeline stage. ASR review remains pending when Back saves ASR and gender data. History and restored queue use one `can_open_review` decision, while the underlying `resume_from` remains the earliest missing stage.
   - Explicit Continue clears the marker only after the edited review checkpoint is valid. Continuing from an ASR review preserves the manual gender checkpoint and starts at the next missing stage; translation review continues at TTS.
   - Tightened compatibility inference for pre-marker records: persisted REVIEW state is authoritative; an old interrupted boundary is inferred only if its saved resume point has not advanced beyond review. Legacy no-record jobs retain checkpoint-based conservative inference. A DONE record suppresses stale review markers.

2. **Crash or metadata save failure at a review boundary**
   - The marker is atomically written before ASR/translation work begins. The orchestrator reopens that pending review before running any later step, even if stage completion or the separate REVIEW metadata transition was interrupted. The marker is cleared only by explicit Continue.

3. **Confirmed local source restart repeats source-changed prompt**
   - Every successful fetch refreshes source identity, including confirmed local-source fetches. Failed fetches never reach the refresh save, so the prior identity remains intact.

4. **Legacy resume with missing original but valid fetched artifact fails on first save**
   - On explicit first save only, a missing original path falls back to the validated fetch checkpoint artifact for source identity. Discovery does not create metadata. Inspection uses that same fetched artifact for identity comparison.

5. **Malformed metadata can abort all history discovery**
   - Progress range checks reject oversized integers before `math.isfinite`; overflow is normalized to `JobRecordError`. Per-entry inspection isolates malformed or unreadable jobs so healthy siblings remain visible.

6. **Malformed review payload can strand the UI**
   - ASR, translation, gender, and analysis checkpoints now validate model construction and field types before they can be offered for review. Invalid payloads are quarantined by the existing checkpoint loader and resume from the earliest invalid step. Review construction failures are caught before hiding the progress window; its close callback restores the main window or queue.

7. **Permissive metadata field types**
   - Schema version now requires a non-boolean integer. File identity size and modification time require non-boolean integers; `null` is rejected.

## Verification evidence

- Manual isolated recovery scenarios passed for: 400-digit progress quarantine and per-job history isolation; malformed `segments: [{}]` invalidation/quarantine and healthy sibling discovery; boolean schema version and null file identity values; local identity refresh after successful confirmed fetch; legacy missing-original discovery without metadata writes and first-resume identity seeded from the validated fetch artifact; invalid-review status becoming interrupted; and DONE records ignoring stale review markers.
- Manual offscreen Qt scenario passed for a simulated review-window constructor exception through both the main-window close callback and the actual batch-queue close callback. In both cases the parent surface was visible and the queue remained blocked/recoverable.
- Manual URL refresh regression passed: a transient forced refresh with partial output and `.part` sidecar preserved the previous downloaded artifact and cleaned unique temporary artifacts; a successful refresh replaced the artifact.
- Manual review-boundary inference passed for pending REVIEW records, crash-before-transition records, approved ASR records resuming at gender, approved records failing after gender, and the explicit-cleared marker overriding stale REVIEW metadata.
- The prior fixer also manually reported these handoff scenarios passing: ASR Back/reopen preserving manual gender and text, translation Back/reopen from restored queue preserving Vietnamese text, crash/failure immediately after each ASR/translation checkpoint and REVIEW metadata write returning to review, and local/legacy identity behavior through history and queue confirmation flows.
- `python -m py_compile` passed for all touched Python modules. `git diff --check` passed.
- No automated test suite was run, per the task instruction. No real provider/video run or OS file-association behavior was exercised.
