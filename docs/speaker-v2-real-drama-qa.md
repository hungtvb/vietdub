# Speaker Verification V2 — real English drama evidence (UNAPPROVED)

Video: existing 13-minute drama used by VietDub CI1; **original private video is
downloaded temporarily during CI**. Neither raw video, audio nor voice
embeddings are uploaded to public build artifacts.

## Grounded source material

- [Actual WhisperX + pyannote Community-1 diarization](https://github.com/hungtvb/vietdub/actions/runs/38887405087): 258 original utterances; 5 pyannote clusters; 148 diarization/ASR QA flags; 64 speaker disagreements.
- [Actual speech embedding + unapproved real drama audit](https://github.com/hungtvb/vietdub/actions/runs/39004634874): 11 real ECAPA embeddings, 18 sampled utterances (10 comparable, 8 overlapping-speaker windows excluded).
- [Clean-reference rerun](https://github.com/hungtvb/vietdub/actions/runs/39004894672): only **9** of the 11 clips have sufficient aligned transcript word evidence and limited overlap to be used for independent scoring. Two clips remain in the listening candidate manifest but are excluded from automated ranking. Embeddings cover **3** scored clusters, while **5** diarization clusters still need human review.
- Full V5 human-written translation draft is a separate local review input, **not APPROVED**. Its 295 lines may split or merge the original 258 ASR utterances. Numeric translated-role IDs do NOT equal verified pyannote actor identities.

## Measured acoustic consistency, not identity accuracy

One ECAPA pass on the genuine English audio reported:

| Measure | Clean-reference rerun |
| --- | ---: |
| Original pyannote clusters | 5 |
| Candidate voice clips | 11 |
| Clips with sufficient word evidence for scoring | 9 |
| Evaluated source utterances | 18 |
| With independent voice similarity scores | 10 |
| Multiple-speaker windows not scored | 8 |
| Median cosine, within same hypothesized pyannote cluster | 0.2511 |
| Median cosine, between different clusters | 0.0127 |
| Confirmed human character identities | **0** |

These values are **uncalibrated similarities**. They do not measure a
speaker-identification accuracy percentage and do not authorize reassigning
any V5 character voice.

An individual pyannote cluster can contain multiple actors. Rare segments
without aligned speech words are potential background/noise and should not
be used as reference voices until heard and checked in the original scene.

## Review contract

The source-ID-aware queue is built by `speaker/real_video_audit.py`.
A V5 line can reference one or multiple original ASR lines; splitting a
source sentence may produce multiple V5 rows. The optional attachment
`attach_ecapa_suggestions(...)` joins raw cosine hints by **original ASR
index**, never by matching translated line number.

Human review sequence:
1. Open the ORIGINAL movie in the VietDub speaker-verification dialog.
2. Listen to voice anchors and inspect the visible speaking character.
3. Verify **specific individual lines**, not entire pyannote clusters.
4. Resolve overlapping speech and short dialogue by scene before assigning voices.
5. Recheck changed scene, source audio, transcript and anchor manifest;
   previously saved decisions are invalidated by changed fingerprints.
6. Only after all required corrections can the translation be separately
   approved and CI2 dubbing be considered.

## Commands

To build a review-only plan from previously extracted real ASR:
`python ci_real_speaker_audit.py --reconciled prior_evidence/asr-reconciled-UNAPPROVED.json --video private_source/film.mp4 --output speaker_v2_real`

For **the existing V5** (if you have its original unapproved JSON) append
`--draft /path/to/your/v5-unapproved.json`. The script validates source-ID
coverage and fails if translated lines were detached from source evidence.
No internet-based paid speaker service is needed: all embeddings are computed
locally from the freely licensed SpeechBrain ECAPA model.

CI workflow: `.github/workflows/vietdub-speaker-real-drama.yml`.
Test suite: `tests/test_real_video_speaker_audit.py`,
`tests/test_speaker_verification_v2.py`.
