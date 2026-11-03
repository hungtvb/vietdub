> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# VietDub reliability hardening design

- Date: 2026-10-25
- Status: implemented and merged; see docs/ARCHITECTURE.md for current behavior
- Selected approach: A — address all four P1 findings with minimal UI changes

## Intent

Make the desktop workflow safe to close, able to recover when checkpoint files
refer to media that has disappeared, safe from accidental output replacement,
and writable when installed under a protected directory such as `Program Files`.
The existing pipeline and its screens should remain familiar.

## Baseline at design time

- `MainWindow.closeEvent` cleans voice-preview temporary directories immediately.
  The download and preview workers run in child `QThread`s, so closing during
  either operation can destroy a still-running thread or remove files it uses.
- Checkpoints validate JSON shape. `Orchestrator.run()` can mark a job done when
  all checkpoint JSON is valid even if a video, WAV, or other referenced file
  was deleted or moved.
- Main-window output names are fixed to `<video>_vidub.mp4`, while
  `media.render` invokes FFmpeg with `-y`. A second run can replace an earlier
  video. The editor chooses a numbered name in its UI, but its export helper
  still needs a no-replace guarantee at the file-writing boundary.
- `JOBS_ROOT` is inside the source/package directory. That may be unwritable in
  a normal Windows install. Settings already use a per-user directory.

## Goals

1. Closing the main window during download or voice preview cannot destroy a
   running thread or clean files still in use.
2. A checkpoint is reusable only when its required output artifacts exist and
   are non-empty. Resume starts at the earliest missing or invalid stage and
   recomputes dependent stages.
3. Pipeline and editor exports never replace an existing user output. On a
   collision, use the next free numbered filename and record the actual path.
   A failed render must not be recorded as complete or leave a partial file
   mistaken for a completed export.
4. New job data lives in a per-user writable data directory on each supported
   platform, rather than beside the installed code.

## Non-goals and anti-goals

- No new settings screen, job browser, or output-path configuration.
- No automatic migration or deletion of old `jobs/` directories; moving large
  job trees on first launch could be slow or fail partway. Existing directories
  remain untouched.
- No deep FFmpeg probe of every checkpoint artifact during resume. Validation
  checks file presence and non-zero size, not that every media file fully
  decodes.
- Do not stop a blocking download/TTS call by terminating its thread. Do not
  overwrite an existing output, even when retrying a render.

## Constraints

- Keep orchestration independent of Qt. UI close safety belongs in the window
  lifecycle; artifact validation belongs in checkpoint/orchestration code.
- Keep the existing job ID and checkpoint format compatible where possible.
- Avoid adding runtime dependencies.
- The output rule covers both MP4 and an SRT sidecar when `sub_mode="srt"`.

## Approaches considered

1. **Reliability pass with the current workflow (selected).** Guard window
   closure until active child workers finish; validate checkpoint artifacts;
   allocate a free numbered export name and enforce no-replace writes; store jobs
   under the platform's user data directory. This covers all four findings
   without adding workflow settings or dialogs beyond a brief close warning.
2. **Add controls for each failure case.** Ask the user whether to wait/cancel
   workers, show missing artifacts and resume choices, prompt for overwrite/name,
   and add a job-directory preference. This offers more control but expands the
   UI and maintenance surface; it was not selected.
3. **Fix only crash and installation blockers.** Guard worker closure and move
   job data, while leaving resume and overwrite behavior unchanged. This is
   smaller but leaves two of the four reported data-loss risks in place.

## Design

### Safe window closure

When either the download or voice-preview thread is still running, ignore the
close event and show a short message asking the user to wait for that operation
to finish. Do not block the UI waiting on a thread and do not attempt unsafe
thread termination. After workers finish, stop/release preview playback before
cleaning its temporary directories and allow the window to close. Keep worker
and thread references valid until the corresponding `finished` signal has been
handled.

### Artifact-aware resume

Keep structural validation for JSON-only steps. Add file validation for stages
that consume or produce files:

- `fetch.video_path` and `extract.wav_path`
- each non-empty `tts` segment `audio_vi` path and `tts_meta.dub_track`
- `mix.mixed_wav`
- `render.video_out`, plus the output SRT sidecar when the effective output
  mode is SRT

Treat missing, non-file, or zero-byte artifacts as an invalid checkpoint. On
resume, find the earliest invalid stage even when a later resume stage was
requested, invalidate that stage and its dependents, then continue from the
earliest invalid stage. The all-checkpoints-complete shortcut must use the same
artifact-aware validation. Keep corrupt JSON handling as it is today.

### No-overwrite export

Use `<stem>_vidub.mp4` when free, then `<stem>_vidub_2.mp4`, `_3.mp4`, and so on.
Check the paired `.srt` name too when SRT output is enabled. Enforce no-overwrite
at the media-writing boundary as well as when selecting a candidate, so a path
collision cannot silently replace an existing file. Only save the render
checkpoint after the MP4 and any required sidecar are complete; persist the
actual selected output path and, for SRT mode, the sidecar output path. Use that
sidecar path when validating render checkpoints. Keep the editor's numbered
naming and apply the same no-replace rule in its export helper.

### Per-user job directory

Resolve the jobs root at runtime using the normal per-user data location:

- Windows: `%LOCALAPPDATA%/VietDub/jobs` (fall back to `%APPDATA%` if needed)
- macOS: `~/Library/Application Support/VietDub/jobs`
- Linux: `$XDG_DATA_HOME/VietDub/jobs`, falling back to
  `~/.local/share/VietDub/jobs`

Create the directory lazily when a job first needs it. Keep settings and model
directories under their existing locations. Leave any old source-adjacent
`jobs/` directory untouched; there is no job-resume browser that needs to scan
or migrate it.

## Acceptance criteria

- An attempted close during download or voice preview leaves the app and worker
  alive; closing after completion exits cleanly and removes preview temp data.
- If a referenced stage file is deleted, rerunning the job does not report
  `DONE`; it restarts at the earliest affected stage and rebuilds downstream
  results.
- Repeating an export with an existing MP4 or SRT sidecar creates a numbered
  output and leaves every existing file byte-for-byte untouched.
- In a packaged install whose application directory is read-only, a new job can
  create its directory and checkpoints under the user data directory.
