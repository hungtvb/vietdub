# Safe Transcript Merge — Implementation Plan

**Goal:** Prevent merging transcript rows with different speaker or audience
labels, which currently drops the second row's labels.

**Architecture:** Keep the validation in `ReviewSourceWindow`, where editable
table values are committed immediately before a merge. Compatible rows follow
the existing merge path unchanged.

## Review focus

- Speaker IDs are compared after reading the current table edits.
- Audience values are compared after the audience dropdown edits are read.
- Rejected merges keep both rows and preserve the table edits in memory.
- Compatible merges preserve existing timing, confidence, and review flags.

## Task 1: Guard transcript row merges

- [x] Add a design spec and implementation plan.
- [x] Reject different speaker IDs with a clear explanation.
- [x] Reject different audience labels with a clear explanation.
- [x] Preserve the existing merge behavior for compatible rows.
- [x] Review the patch and run static syntax/diff checks.

**Verification note:** Automated tests are not added or run in this task.
