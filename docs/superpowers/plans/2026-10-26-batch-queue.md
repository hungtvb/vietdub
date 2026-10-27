> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# Sequential Batch Queue — Implementation Plan

## Goal

Add a first same-session batch workflow for local videos while keeping the
single-job orchestrator independent of queue state.

## Task 1: Add callback hooks to the existing progress window

- Add optional progress/result callbacks to `ProgressWindow`.
- Keep existing single-job callers and screen transitions unchanged.
- Emit callbacks on the Qt/UI thread after receiving runner signals.

## Task 2: Build the batch queue window

- Add multiple local videos with canonical-path duplicate detection.
- Display filename, status, and overall percentage.
- Support remove and reorder before start.
- Create and process one `Job` at a time.
- Hold the queue at review/pause/failure/cancel until the current job is
  continued, retried, or explicitly skipped.
- Return control to the queue when the user dismisses a completed result window
  with either the action button or the window close control.

## Task 3: Integrate the queue entry point into the main screen

- Reuse provider validation and project settings from the existing start flow.
- Add a secondary “Hàng đợi” action beside single-video processing.
- Keep the main window hidden only while the queue window is active.

## Constraints

- Do not change `Orchestrator` to know about batches.
- Do not run jobs concurrently.
- Do not persist or claim restart recovery for the queue in phase 1.
- Preserve existing one-video behavior and review screens.
- No tests are added or run in this task; use static review and compile checks.

## Review focus

- A queue item that reaches `REVIEW` must not trigger the next item.
- Reopening a queue item in `REVIEW` must show its review UI again, not advance
  directly from the saved next-step checkpoint.
- Closing a paused/failed/cancelled progress window must return control to the
  queue without losing the job or its checkpoint.
- A deliberate skip must be distinguishable from completion.
- The one-video `start_job()` flow must still preserve an already downloaded
  URL job's ID and directory.
