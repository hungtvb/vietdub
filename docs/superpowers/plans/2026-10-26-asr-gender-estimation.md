> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# ASR Review Gender Estimation Follow-up

## Goal

After a user continues from source transcript review, the pipeline must still run automatic gender estimation for speakers left unlabeled while preserving explicit manual gender choices.

## Scope

- Keep source review edits durable across Back, close, restart, and Continue.
- Do not treat an unfinished review input as a completed gender-estimation stage.
- Resume through the gender stage after ASR review approval.
- Merge estimated results with explicit manual labels, with manual labels taking precedence.
- Invalidate saved review inputs when rebuilding from ASR or an earlier stage.
- Preserve translation-review behavior and compatibility with existing jobs that saved source-review edits in `gender.json`.

## Acceptance

1. A source review with all genders left blank resumes through the automatic estimator.
2. A mixed review estimates blank speakers and preserves manually selected male/female labels.
3. Back/close/reopen keeps manual text and gender edits, without marking gender estimation complete.
4. Rebuilding ASR or an earlier stage clears stale source-review inputs.
5. Translation review still resumes at TTS.
6. Verify with disposable/offscreen manual scenarios, `python -m py_compile`, and `git diff --check`. Do not add or run automated tests unless requested.

## Workflow

Implement as one subagent task, then request one fresh read-only reviewer. Do not push or merge without a separate request.
