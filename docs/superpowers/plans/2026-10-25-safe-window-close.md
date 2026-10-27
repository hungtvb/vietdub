> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# Safe Window Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let VietDub close safely after transient download and voice-preview workers finish, without destroying a live `QThread` or deleting files still in use.

**Architecture:** Keep the worker lifecycle in `ui/main_window.py`. The window ignores a close request while either transient thread is active; it does not block the UI or terminate a worker. Once both threads stop, release preview playback and clean the temporary directories before accepting close.

**Tech Stack:** Python, PySide6 (`QMainWindow`, `QThread`, `QMediaPlayer`).

**Spec:** [Reliability hardening design](../specs/2026-10-25-reliability-hardening-design.md)

## Global Constraints

- Keep orchestration independent of Qt.
- Avoid adding runtime dependencies.
- Do not stop a blocking download/TTS call by terminating its thread.
- Closing during a running transient worker shows a brief wait message and leaves the window open.

## Review Focus

- URL download still writes to the job directory when close is requested — confirm close is ignored and the download can finish.
- Voice preview is still synthesizing — confirm close is ignored and its temporary directory remains available.
- Preview synthesis finished but audio is playing — confirm playback is stopped and its source released before cleanup.
- A `QThread` reference remains after its thread finished — confirm close is accepted because `isRunning()` is false.
- No transient worker was ever started — confirm ordinary close remains unchanged.

---

### Task 1: Guard transient worker shutdown

**Files:**
- Modify: `ui/main_window.py:122-127, 562-570`

**Interfaces:**
- Produces: `MainWindow._transient_workers_running() -> bool`, which checks `_dl_thread` and `_pv_thread` when they are non-`None`.

- [ ] **Step 1: Add `_transient_workers_running()`**

  Return `True` if either retained thread exists and `isRunning()` is true. Treat a missing or finished thread as inactive.

- [ ] **Step 2: Guard `closeEvent()`**

  Before touching preview state, ignore the close event and show a short Vietnamese wait message when `_transient_workers_running()` is true. Do not wait synchronously or call `terminate()`.

- [ ] **Step 3: Release playback before cleaning preview temporary directories**

  When no worker is active, stop `_player`, clear its current source, then clean `_pv_tmps` and clear the list. Keep the existing normal close behavior.

- [ ] **Step 4: Manually verify the five Review Focus cases**

  Check closing during download, during preview synthesis, during preview playback, after a worker has finished, and with no worker created. Confirm the window remains responsive while a worker finishes.

- [ ] **Step 5: Commit the completed task**

  ```bash
  git add ui/main_window.py
  git commit -m "fix: guard main window close during transient workers"
  ```

**Verification note:** This plan uses manual acceptance checks only; it does not add or run tests.
