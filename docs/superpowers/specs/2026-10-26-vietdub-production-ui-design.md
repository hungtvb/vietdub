> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# VietDub Production Desktop UI — Design

**Status:** Implemented and merged. This file records the original design rationale; the running UI is documented in [README.md](../../README.md).

## Intent

Bring VietDub's full PySide6 desktop workflow to a production standard: make the source, review, processing, finish, settings, and editor screens feel like one deliberate product; keep the app usable as windows resize; and make editing and failure states clear. The web UI remains out of scope. Existing dubbing, translation, export, and review behavior stays intact unless a current UI path can lose user edits or show invalid state.

## User and context

VietDub is a Vietnamese desktop tool for dubbing videos. Users select a local video or link, review recognized speech and translated subtitles, watch processing, inspect the output, and make final timeline/subtitle/logo adjustments. The app uses PySide6 and already has an Apple-inspired light appearance. The user has asked for an Apple desktop feel, one consistent background from the main tool through the editor, professional product quality, and reliable resizing.

## Audit ranking

### P1 — fix first

1. Large surfaces and styles drift between the main workflow and editor; the user also requires a consistent app canvas. Several normal-size blue labels/buttons fall below 4.5:1 contrast, and button/table focus states are not explicit.
2. Editor layout adapts only by width, keeps rigid minimum panels, and its custom timeline has no keyboard operation or visible alternative to dragging. Several workflow windows also have narrow fixed minima and horizontally packed actions.
3. Leaving either review screen can discard edits. Selecting an unreadable video can leave the previous ready-to-run state visible.

### P2 — include in the same pass where it fits

1. The editor always claims a draft is auto-saved even after a save error, and video-preview failures have no actionable state.
2. Long review rows are clipped at fixed heights; the settings connection check and some media metadata work can block the interface.
3. Success dialogs interrupt routine actions where inline feedback would be clearer.

## Goals

- Use one shared application canvas, `#F5F5F7`, across all workflow windows and the editor. Keep large content containers on that canvas; reserve contrasting surfaces for editable controls/tables and the actual video preview.
- Consolidate colors and component states in shared semantic tokens. Use platform UI fonts, a 4/8 spacing rhythm, strong text contrast, visible keyboard focus, and Vietnamese labels.
- Rework the existing screens in place so their hierarchy and spacing feel intentional without changing the dubbing pipeline or introducing a web surface.
- Adapt key layouts by both window width and height. Keep the primary action, current state, and a way to reach hidden panels usable at compact sizes.
- Preserve review edits when leaving a screen and report true save, preview, download, connection, and export states with a recovery action where applicable.
- Keep the timeline's existing trim, seek, subtitle move/resize, logo, and subtitle editing features; add keyboard/button alternatives for drag-only operations.

## Non-goals

- Reintroducing or changing the removed web UI.
- Changing ASR, translation, TTS, model selection, job orchestration, or output formats.
- Building a full multitrack NLE, waveform engine, or thumbnail-generation system.
- Adding a new UI dependency or downloading custom fonts.

## Constraints

- Keep the existing Python/PySide6 application entry point and application data contracts.
- Keep all user-facing copy in Vietnamese.
- The app background must remain `#F5F5F7` from the main window through the editor; the video preview may retain its dark media background.
- Do not add runtime dependencies.
- Prefer platform-native fonts and controls; a CSS/UI recommendation that targets landing pages or an unsupported Qt stack is not applicable.

## Responsive target

Keep the current per-window minimum sizes as the supported compact boundary: main `620×500`, settings `620×480`, processing `650×500`, source review `700×500`, translation review `700×520`, finish `650×500`, and editor `650×560` Qt logical pixels. This is a builder call based on the existing product constraints; do not raise those minima just to avoid responsive work. Manually inspect at each window's minimum size and at `1280×800`. Use Qt logical geometry and platform UI fonts so system scaling continues to work; this pass does not claim a separate OS/DPI certification matrix.

## Approaches

### A. Refine the current PySide6 screens around one shared design system — selected

Keep the existing windows and their signals, centralize visual tokens, then refactor the main/settings/finish, review/progress, and editor surfaces in independent steps. This preserves the known pipeline and limits regression risk while addressing the audit findings. The user selected approach A and approved it in the conversation.

### B. Replace all screens with a new navigation and custom widget architecture

This would permit a larger visual redesign, but it changes many window and callback lifecycles at once and makes data-loss regressions harder to isolate. It is unnecessary for the requested production pass.

### C. Change only global stylesheets

This is the least expensive approach, but it would leave review data loss, editor resizing, keyboard access, and misleading save/preview states unresolved.

## Design direction

The UI/UX Pro Max design-system search returned landing-page patterns twice, and its stack list does not include PySide6. Those matches are not a verified desktop-app fit, so they are not being persisted or applied. Use the user's existing Apple desktop direction and stack-agnostic accessibility/layout guidance as the fallback.

- **Canvas:** `#F5F5F7` for every screen's root and large work area; no screen-specific canvas. Use spacing, typography, subtle dividers, and alignment for hierarchy instead of stacking white cards.
- **Text:** primary `#1D1D1F`; secondary `#515158`; platform UI font at a 10 pt body baseline, with captions no smaller than 9 pt.
- **Action:** accessible blue `#0066CC` with white text; hover/pressed/focus variants remain semantic. This gives at least 5.1:1 contrast on the app canvas and 5.5:1 on white controls.
- **Control/special surfaces:** white for editable fields and focused tables; dark only for the video preview; semantic success/warning/error colors are paired with labels or icons.
- **Layout:** 4/8 spacing rhythm, clear screen title + context, one primary action per step, compact secondary actions, content that wraps or scrolls instead of clipping.
- **Motion:** restrained and interruptible; no decorative animation required for this pass.
- **Interaction:** visible focus, descriptive names/tooltips for icon controls, keyboard routes for timeline actions, clear disabled/loading/error/success states.

## Scope by surface

- **Main:** clear source selection, concise project setup, progressive options, reliable valid-video state, responsive footer action.
- **Settings:** consistent sections and compact form hierarchy; connection checks show progress/results without freezing the window.
- **Processing and review:** clear progress hierarchy and adaptive log/step panels; readable long subtitles; preserve edits on Back/window close.
- **Finish:** make preview, output locations, and next actions easy to scan at narrow sizes.
- **Editor:** keep the preview, inspector, and timeline usable at compact width and short height; expose real autosave and playback errors; keep the current edit actions reachable by keyboard or explicit controls.

## Acceptance criteria

1. Main, workflow, review, finish, settings, and editor roots all use the shared `#F5F5F7` canvas; large cards do not recreate separate page backgrounds.
2. Main and editor styles consume the same semantic palette and include a visible keyboard focus state. Normal text and action labels meet 4.5:1 contrast on their actual surfaces.
3. At each window's existing minimum size and at `1280×800`, content wraps, scrolls, or switches layout; primary actions and required controls never disappear behind clipped/fixed regions.
4. Back and window-close paths from both review screens preserve the edited checkpoint data or keep the user on screen with a clear save error.
5. An unreadable replacement video cannot leave the previous video marked ready; its error includes a recovery path.
6. Editor draft status reflects the result of saving; preview failures are visible and recoverable; timeline drag actions have an accessible alternative.
7. Existing screens remain desktop PySide6 screens, all user-facing copy stays Vietnamese, and no runtime dependency is added.

## Risks and validation

Qt stylesheets can suppress native focus and size behavior, so validate focus and resizing on the actual widget layouts. Manually inspect the main window, settings, review, progress, finish, and editor at the sizes in the Responsive target section. Do not add or run an automated test suite for this UI pass; run only static syntax validation and focused manual interaction checks requested by the user.
