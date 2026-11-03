> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# Per-User Job Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep new job data writable when VietDub is installed in a protected application directory.

**Architecture:** Resolve the platform's per-user data directory in a small core helper and point `JOBS_ROOT` there. `Job.job_dir` continues creating each job lazily; settings and model locations remain unchanged.

**Tech Stack:** Python, `pathlib`, standard-library `os` and `sys`.

**Spec:** [Reliability hardening design](../specs/2026-10-25-reliability-hardening-design.md)

## Global Constraints

- Avoid adding runtime dependencies.
- Create the directory lazily when a job first needs it.
- Keep settings and model directories under their existing locations.
- Leave any old source-adjacent `jobs/` directory untouched; do not migrate or delete it.
- Keep the existing job ID and `jobs/<job_id>/` structure.

## Review Focus

- Windows `LOCALAPPDATA` is set — jobs resolve under `%LOCALAPPDATA%/VietDub/jobs`.
- Windows `LOCALAPPDATA` is absent but `APPDATA` is set — use the documented fallback.
- macOS path resolution — use `~/Library/Application Support/VietDub/jobs`.
- Linux `XDG_DATA_HOME` is set or absent — use it or `~/.local/share/VietDub/jobs` respectively.
- The application directory is read-only — job creation still succeeds in the user data directory.

---

### Task 1: Resolve and use the per-user job directory

**Files:**
- Create: `core/paths.py`
- Modify: `core/job.py:24-25, 48-52`

**Interfaces:**
- Produces: `user_data_dir() -> Path`, returning the platform data root without creating it.
- `core.job.JOBS_ROOT` becomes `user_data_dir() / "jobs"`; tests and callers can continue overriding `JOBS_ROOT` as they do today.

- [ ] **Step 1: Implement `user_data_dir()`**

  Return `%LOCALAPPDATA%/VietDub` on Windows, falling back to `%APPDATA%/VietDub`; return `~/Library/Application Support/VietDub` on macOS; return `$XDG_DATA_HOME/VietDub` or `~/.local/share/VietDub` on Linux. Use a home-directory fallback if the relevant Windows variables are absent. Do not create directories in this function.

- [ ] **Step 2: Point `JOBS_ROOT` to the user data directory**

  Import `user_data_dir()` in `core/job.py` and set `JOBS_ROOT = user_data_dir() / "jobs"`. Preserve lazy creation through the existing `Job.job_dir` property.

- [ ] **Step 3: Manually verify platform resolution and lazy creation**

  Inspect the resolved path for each platform environment case in Review Focus. Confirm importing `core.job` does not create the directory, while accessing `Job.job_dir` does. Confirm the old source-adjacent `jobs/` tree is untouched.

- [ ] **Step 4: Commit the completed task**

  ```bash
  git add core/paths.py core/job.py
  git commit -m "fix: store job data in the user data directory"
  ```

**Verification note:** This plan uses manual acceptance checks only; it does not add or run tests.
