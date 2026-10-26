# Safe Transcript Merge — Design

## Intent

Prevent the source transcript review from silently changing who spoke a line
or who it is addressed to when two rows are merged.

## Current behavior

`ReviewSourceWindow.merge_with_next()` joins the selected row with the next
row, keeps the first row's speaker and audience, and deletes the second row.
When those labels differ, the merged transcript misattributes part of the
dialogue and discards a human review decision.

## Design

- Commit the active table editor and read the current row values first.
- Merge only when both rows have the same speaker ID and the same audience
  value.
- If either label differs, show a concise explanation and leave both rows
  intact. The edits already committed to the table remain visible and in the
  in-memory segments, so the user can correct labels and retry.
- Preserve existing timing, confidence, and `needs_review` merge behavior.
- If the first row has no gender value, carry the second row's value when
  merging; speaker gender is not a reason to reject a merge.

## Non-goals

- Do not infer whether rows are one utterance from audio or timestamps.
- Do not change the segment schema, analysis prompts, or automatic ASR merge.
- Do not add a confirmation flow or change how compatible rows merge.

## Acceptance criteria

- Different speaker IDs block the merge and both transcript rows remain intact.
- Different audience values block the merge and both rows retain their values.
- Matching speaker and audience values merge using the current timing and
  review-flag behavior.
- A blocked merge does not revert edits made in the active table editor.
