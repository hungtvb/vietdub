# VietDub Production Desktop UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine every VietDub desktop screen into one responsive, accessible Apple-inspired product UI while preserving the current dubbing workflow.

**Architecture:** Keep the existing PySide6 windows, signals, and job data contracts. Establish shared semantic appearance tokens first, then update the entry/settings/output screens, processing/review screens, and editor in separate reviewed tasks.

**Tech Stack:** Python, PySide6/Qt, existing VietDub UI modules; no new runtime dependency.

**Spec:** `docs/superpowers/specs/2026-10-26-vietdub-production-ui-design.md`

## Global Constraints

- Keep the web UI removed; update only the native PySide6 application.
- Use one application canvas color, `#F5F5F7`, from the main screen through the editor; reserve local contrast for editable controls/tables and the video preview.
- Preserve the existing user-facing workflow, Vietnamese copy, and pipeline data contracts.
- Do not add runtime dependencies or change ASR/translation/TTS/job behavior.
- Keep platform UI fonts, 4/8 spacing rhythm, visible keyboard focus, and accessible text contrast.
- Preserve review edits when leaving the source-review or translation-review screen.
- Keep the current timeline edit features; provide keyboard or explicit-control alternatives to drag-only actions.
- Do not add or run automated tests for this pass; use static syntax validation and focused manual resize/interaction checks.

## Review Focus

1. A window resized to its existing minimum size or shortened until the editor timeline is constrained; verify controls remain reachable and no action/footer is clipped (Task 4; Task 2 and Task 3 responsive screens too).
2. A long subtitle/source line selected or edited in either review table; verify the full text remains readable and editable (Task 3).
3. A review edit followed by Back or window close, including a failed save; verify edits persist or the screen stays open with recovery guidance (Task 3).
4. A valid video followed by an unreadable replacement file; verify the old ready state is cleared and the user can select another file (Task 2).
5. A draft write, preview decode, or connection-check failure; verify the UI reports the actual state and a recovery path (Task 2 and Task 4).

---

### Task 1: Shared design tokens and focus states

**Files:**
- Modify: `ui/theme.py`
- Modify: `ui/editor_style.py`

**Interfaces:**
- Produces: `UI_COLORS` in `ui.theme`, a semantic `dict[str, str]` containing `canvas`, `text`, `secondary_text`, `primary`, `primary_hover`, `primary_pressed`, `border`, `control`, `media`, `success`, `warning`, `danger`, and `focus`.
- Keeps: `APP_BACKGROUND`, `APPLE_STYLESHEET`, `apply_apple_theme(app)`, and `EDITOR_STYLESHEET` available to existing callers.

- [x] **Step 1: Define semantic colors and type/layout tokens** in `ui/theme.py`; set `APP_BACKGROUND` from `UI_COLORS["canvas"]`, keep root and large content surfaces on the same canvas, and use a 10 pt platform-font baseline with no caption below 9 pt.
- [x] **Step 2: Add consistent control states** for default, hover, pressed, disabled, focus, selected rows, tabs, and destructive actions; set the primary blue to `#0066CC` and avoid removing table focus without a replacement.
- [x] **Step 3: Make editor styling consume the shared tokens** in `ui/editor_style.py`; retain the dark media preview and avoid separate large white editor/root surfaces.
- [x] **Step 4: Review token usage and contrast** with a focused static inspection of the touched styles; confirm all controls still have distinct states and no raw per-screen palette has been added.
- [x] **Step 5: Commit** as `style: unify VietDub desktop design tokens`.

### Task 2: Main, settings, and finish screens

**Files:**
- Modify: `ui/main_window.py`
- Modify: `ui/settings_dialog.py`
- Modify: `ui/finish.py`

**Consumes:** `UI_COLORS`, `APP_BACKGROUND`, and `APPLE_STYLESHEET` from Task 1.

- [x] **Step 1: Refine the main screen hierarchy** into a concise source-first workflow with progressive options and a responsive primary-action footer; retain local-file drag/drop, link download, voice preview, and existing settings.
- [x] **Step 2: Move video metadata probing off the UI thread** using a `VideoInfoWorker(QObject)` that emits `(path, info_dict)` or `(path, error_text)`; clear the current ready state before probing a replacement, report progress inline, and only enable “Bắt đầu lồng tiếng” after the current file validates.
- [x] **Step 3: Make settings usable at compact sizes** with the shared canvas and clear labels; move the Ollama connection request to a worker, disable the check control while it runs, and show success/error inline with a recovery path.
- [x] **Step 4: Refine finish preview and output actions** so paths wrap/elide safely and primary/secondary actions remain reachable after resize.
- [x] **Step 5: Manually inspect** the main/settings/finish windows at each existing minimum size and at `1280×800`; verify no footer, tab, path, or action is clipped.
- [x] **Step 6: Run static syntax validation** on the changed Python modules, then commit as `style: refine setup and output screens`.

### Task 3: Processing and review screens

**Files:**
- Modify: `ui/progress.py`
- Modify: `ui/review_source.py`
- Modify: `ui/review_vi.py`

**Consumes:** `UI_COLORS`, `APP_BACKGROUND`, and `APPLE_STYLESHEET` from Task 1.

- [x] **Step 1: Refine processing hierarchy and panel behavior**; keep progress/status prominent, make step/log areas adapt by width and height, and keep pause/resume/cancel actions reachable.
- [x] **Step 2: Make long source and translated subtitle rows readable** with wrapping and content-aware row sizing while keeping selection, inline editing, playback, split/merge, metadata, and navigation behavior.
- [x] **Step 3: Persist source-review edits before Back or close** by committing any active cell editor, reusing `_read_table()`, and writing the current `asr` segments plus `gender` speakers; on invalid data or save failure, keep the review open and show the failing field/action.
- [x] **Step 4: Persist translation-review edits and metadata before Back or close** by committing any active cell editor and writing `translate` segments plus the current video metadata; on save failure, keep the review open and preserve the edited widgets.
- [x] **Step 5: Manually inspect** progress/review screens at normal and compact widths; edit a long subtitle, leave via Back and close, then confirm saved content remains when reopened; check the failure path by reviewing error handling statically if a write fault cannot be induced safely.
- [x] **Step 6: Run static syntax validation** on changed modules, then commit as `style: improve processing and review screens`.

### Task 4: Responsive, accessible editor

**Files:**
- Modify: `ui/editor.py`
- Reuse: shared `EDITOR_STYLESHEET` and `UI_COLORS` from Task 1.

**Consumes:** the shared palette and focus states established in Task 1.

- [x] **Step 1: Adapt preview, inspector, timeline, and footer** to both width and height; preserve every current tool and ensure narrow/short windows do not crop primary controls.
- [x] **Step 2: Add keyboard/button alternatives and accessible labels** for timeline seek, trim, and subtitle timing changes; focused timeline `Left`/`Right` seeks by 1 second, `Shift+Left/Right` by 0.1 second, `Home/End` seeks to the video bounds, and labeled numeric trim controls expose the same in/out values as the drag handles; keep the existing drag gestures.
- [x] **Step 3: Make draft and media feedback truthful**: reflect saving/saved/error states from `_save_draft`, expose preview loading/failure with a retry/recovery action, and keep export progress/status clear.
- [x] **Step 4: Manually inspect** the editor at normal, compact, and short-window sizes; navigate timeline controls by keyboard and confirm preview/save errors remain visible and recoverable by static path review where failures cannot be induced safely.
- [x] **Step 5: Run static syntax validation** on the changed module, then commit as `style: make editor adaptive and accessible`.
