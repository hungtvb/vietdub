> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# Safe Transcript Merge — Implementation Plan

**Goal:** Prevent merging transcript rows with different speaker/audience
labels or conflicting non-empty gender values, which currently drops the
second row's metadata.

**Architecture:** Keep the validation in `ReviewSourceWindow`, where editable
table values are committed immediately before a merge. Compatible rows follow
the existing merge path unchanged.

## Review focus

- Speaker IDs are compared after reading the current table edits.
- Audience values are compared after the audience dropdown edits are read.
- Conflicting non-empty speaker-gender values are rejected instead of discarded.
- Rejected merges keep both rows and preserve the table edits in memory.
- Compatible merges preserve existing timing, confidence, and review flags.

## Task 1: Guard transcript row merges

- [x] Add a design spec and implementation plan.
- [x] Reject different speaker IDs with a clear explanation.
- [x] Reject different audience labels with a clear explanation.
- [x] Preserve the existing merge behavior for compatible rows.
- [x] Review the patch and run static syntax/diff checks.

**Verification note:** Automated tests are not added or run in this task.
