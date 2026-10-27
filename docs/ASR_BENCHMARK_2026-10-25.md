# ASR comparison — 2026-10-25

> Đây là benchmark lịch sử trên một video, đánh giá định tính và không có transcript chuẩn. Nó không bao gồm VietDub STT local được thêm sau đó; kết quả không đại diện cho mọi nguồn/video hoặc máy.

## Real video used

The comparison used the public Wikimedia ChinaJoy video linked from
`tests/batch_20.py` (`2025_ChinaJoy上海启幕_AI技术赋能游戏新场景.webm`). The
source is 185 seconds; every model received the same first 120 seconds of
16 kHz mono audio. The segment contains Mandarin narration and interviews,
including game and robotics names. Runtime was measured on CPU in the test
environment; cold model startup and transcription are reported separately
where available.

There were no verified subtitles for this video, so transcript quality below
is a qualitative review of the model outputs, not a CER/WER score.

## Results

| Backend | Result on the clip | Runtime | Speakers / timestamps |
|---|---|---:|---|
| FunASR SenseVoiceSmall + VAD/punctuation/CAM++ | 49 segments; mostly coherent; some awkward phrase splits and more errors on names | 46.7 s | 3 speakers; timestamps |
| FunASR SeacoParaformer + same VAD/punctuation/CAM++ | 47 segments; quality close to SenseVoice, with a few different word choices | 53.0 s | 3 speakers; timestamps |
| Whisper large-v3-turbo, int8 | 44 segments; cleaner sentence segmentation and better recognition of names such as `黑神话`, `明末`, `N1馆`, and `Robo Cup`; still has errors | 52.9 s decode + 3.7 s load | Timestamps; no speaker labels |
| Qwen3-ASR-0.6B | Full Chinese transcript; likely errors in interview and robot wording, but it correctly produced `以期重构未来` where Whisper made an error | 179.0 s decode + 15.4 s load | No timestamps or speaker labels |
| Qwen3-ASR-1.7B (bfloat16 CPU) | Full Chinese transcript; improved some phrases over 0.6B, but still confused interview words/names | 211.9 s decode + 1.3 s load | No timestamps or speaker labels |
| VietDub hybrid (Whisper + FunASR/CAM++) | 44 Whisper segments; speaker sequence `0 → 1 → 0 → 2 → 0` matched narration/interview turns | 104.5 s end-to-end on cached weights | 3 speakers; timestamps |

Whisper's notable errors included `仪器重构未来` for a phrase likely intended
as `以期重构未来`, and a misrecognition around the Robo Cup interview. Qwen
got `以期重构未来` right, but its output also included likely errors such as
`站站起来了`, `三大座`, and `美球毕竟`. These judgments are based on listening
context and model agreement, not verified subtitles. The FunASR transcripts
sometimes split or punctuated phrases less naturally. The two FunASR models
were close enough that this single video does not establish a consistent
winner between them.

### Qwen3-ASR details

Both Qwen sizes processed the same 120-second WAV, detected Chinese, and
returned one continuous transcript rather than timed segments. Qwen 0.6B
rendered figures as spoken Chinese (for example, `743家` as `七百四十三家`),
but returned likely errors such as `站站起来了`, `三大座`, and `美球毕竟`.
It correctly produced `以期重构未来` where Whisper returned `仪器重构未来`.

Qwen 1.7B was run on CPU in bfloat16. A float32 load exceeded this environment's
8 GB memory limit, while bfloat16 loaded successfully. It improved some phrases:
`三大作` instead of Qwen 0.6B's `三大座`, and `弓着身子` in the robot narration.
It still returned likely errors such as `汉人化了` and `名模的那些设计质量`;
Whisper instead produced the plausible game names `黑神话` and `明末`. Qwen 1.7B
also returned `以期重构未来游戏生态` correctly. Without verified subtitles,
these are qualitative examples, not a definitive accuracy score.

Qwen 1.7B was not selected as the pipeline default: it took 211.9 seconds for
120 seconds of audio on CPU and did not supply timestamps or speaker labels.
Its text is competitive and appears better on some phrases, while Whisper
provided more useful segmentation and timestamps for the current CAM++ pipeline.

## Tuning each candidate

The settings below were compared on the same ChinaJoy WAV. There are no gold
subtitles, so a change is retained only when it preserved the useful transcript
and pipeline output.

### Whisper large-v3-turbo

- Keep `beam_size=5` and `condition_on_previous_text=False`.
- Use the project's source-language setting (`zh`) instead of spending effort
  on language detection; the model still detected Chinese at 0.998 probability
  in the earlier run.
- Keep silence VAD filtering off. With it on, Whisper returned 46 segments and
  changed `新国际博览中心` to `新国际波兰中心`; with it off, it returned 44
  segments and retained `新国际博览中心`. It did not improve the tested
  recognition time enough to justify that error.
- Pass user-supplied project proper nouns as an optional initial prompt. The
  tested names did not change this clip's transcript, so they are only hints,
  not automatic corrections.

The tuned hybrid ran in 104.5 seconds with cached model weights, returned 44
segments and three speakers, and preserved `0 → 1 → 0 → 2 → 0`. One overlapping
Whisper interval was clipped and marked for review. The earlier auto-language
hybrid took 109.5 seconds; these are single CPU timings and should not be read
as a guaranteed speedup.

### Qwen3-ASR-1.7B

- Use bfloat16 on this CPU: a float32 load exceeded the environment's 8 GB
  memory cap. The successful 1.7B run took 211.9 seconds in bfloat16.
- Use a Chinese language hint and, when supplied by the project, a short list
  of proper nouns as context. The combined hinted run normalized `N一馆` to
  `N1馆`, but took 228.8 seconds and still misrecognized parts of the interview.
  The test does not isolate the language hint from the vocabulary context.
- Do not use it as the current pipeline backend: it returns a continuous
  transcript without timestamps or speaker IDs. Adding those requires a
  separate aligner and diarization pass.

### FunASR / SenseVoiceSmall

- Keep automatic language detection. Forcing `language="zh"` on this clip
  produced 41 segments with visibly worse wording, including `一大座` and
  `一汽重构`.
- Keep the existing dynamic batch default (`batch_size_s=300`). Enabling
  `merge_vad` returned 49 segments with similar wording and no clear accuracy
  improvement, so it is not enabled.
- Retain VAD, punctuation, and CAM++ because FunASR supplies the speaker turns
  needed by the Whisper pipeline and remains the direct, faster alternative.

An additional 66-second Henan flood clip from the same test manifest was
unsuitable for this Chinese comparison: Whisper classified it as English
(probability 0.76) and produced unrelated filler, Qwen3-ASR-0.6B returned no
text, and FunASR output was mostly gibberish. It was excluded from the ranking.

## Pipeline choice

The default pipeline now uses Whisper for words and sentence timestamps, then
maps each timestamp to the CAM++ speaker turn with the greatest time overlap.
On the test clip, the mapping preserved the narration/interview turn changes
across three speakers. The hybrid pass is slower than running one ASR model
alone because it runs diarization and transcription sequentially. The app
releases each model before loading the other to limit peak memory. If Whisper
fails or returns no usable segments, the transcript falls back to FunASR and
is marked for review. Users can choose direct FunASR in Settings.

The 104.5-second tuned hybrid measurement includes FunASR diarization, Whisper
model load from local cache, and Whisper decoding. It excludes the initial
download of model weights. One overlapping timestamp was clipped to the next
segment's start; the final result contained 44 usable segments and one review
flag.

The earlier 4.2-second Qwen model-card sample produced exact matches from
several models, but it was not representative enough to choose a production
default. The real video comparison is more relevant, while still only one
public clip. Validate with the user's own video and verified subtitles to
measure actual recognition error rates. Qwen3-ASR-1.7B was run on this clip
in bfloat16; its earlier float32 load exceeded the environment's memory limit.

## Cross-video verification

The three shortlisted systems were run on three additional public Mandarin
videos from Wikimedia Commons. All short samples were the same 60-second
16 kHz mono WAV window. Whisper used forced Chinese, beam size 5, no previous
text conditioning, and VAD off; SenseVoice kept automatic language detection;
Qwen3-ASR-1.7B used bfloat16 on CPU with a Chinese language hint and no
video-specific vocabulary context.

| Clip / window | SenseVoice | Whisper large-v3-turbo | Qwen3-ASR-1.7B | Observation |
|---|---|---|---|---|
| Zhejiang school news, 0–60 s | 40.0 s; 12 segments | 4.3 s load + 26.6 s decode; 18 segments | 80.3 s | Qwen captured more of the student exchange; this window alone has no trustworthy score. |
| Ma Jian VOA interview, 0–60 s | 33.3 s; 18 segments | 3.8 s load + 24.4 s decode; 20 segments | 65.0 s | The three transcripts agreed on the main argument; there is no reference transcript for scoring. |
| Danba bean farms, 0–60 s | 31.7 s; 34 segments | 3.5 s load + 28.4 s decode; 21 segments | 112.7 s | All three confused the crop name; the Commons description spells it `黄金荚`. |
| Danba, 58–118 s (local interviews) | 41.5 s; 23 segments; 3 speakers | 4.8 s load + 23.9 s decode; 15 segments | 102.7 s | SenseVoice and Qwen transcribed the local-accent speech near the start; Whisper returned almost no text for the first 30 seconds of this window. |

The Zhejiang clip has a published interview script, so all three systems were
also evaluated on the full 184.8-second source. The character error rate uses
Levenshtein distance after removing punctuation and whitespace and excluding
the script's speaker labels. This is an editorial transcript rather than
time-aligned subtitles, so small script/audio differences may affect the
score.

| System | CER against 714 reference characters | Decode / load time | Segments / speakers |
|---|---:|---:|---|
| SenseVoiceSmall + VAD/punctuation/CAM++ | 21.4% | 68.1 s total | 60 / 2 |
| Whisper large-v3-turbo int8 | 19.6% | 65.0 s decode + 4.3 s load | 69 / no speaker labels |
| Qwen3-ASR-1.7B bfloat16 | **14.7%** | 346.6 s decode + 0.8 s load | Continuous text; no timestamps or speaker labels |

Qwen won on text accuracy against this published script and also retained more
of the local-accent interview than Whisper in the Danba sample. It still
mis-spelled the principal's name (`刘永武`; the source script says `刘勇武`),
while Whisper got that name right. Qwen took about 5.8 minutes end to end,
roughly 5 times the Whisper wall time on the full Zhejiang clip. The raw Qwen
model still returns no sentence timestamps or speaker IDs; the optional
aligner/CAM++ adapter described below supplies them. The current hybrid remains
the practical dubbing default because it is much faster.
SenseVoice remains useful as a fallback: it retained the local-accent speech
that Whisper mostly omitted in the Danba window. This evidence is stronger
than the earlier one-clip comparison, but only one of the four video sources
had a usable reference transcript, so it does not establish a universal
accuracy ranking.

## Adding timestamps and speakers to Qwen

Qwen3-ASR itself returns continuous text. The optional app backend now pairs
it with `Qwen/Qwen3-ForcedAligner-0.6B` for character-level timing, groups
aligned characters at punctuation/pauses into VietDub sentences, and assigns
each sentence the CAM++ speaker with the greatest time overlap. FunASR/CAM++,
Qwen ASR, and the aligner load one at a time to control peak RAM.

The integrated adapter was run on the Danba local-interview window (58–118 s):
it returned 10 timed sentences across 3 speaker IDs in 166.3 seconds end to
end. Supplying the project term `黄金荚` also corrected that crop name in the
Qwen text. The stand-alone aligner took 16.9 seconds after its model was
cached; its first download/load took 125 seconds in this environment. On the
full 184.8-second Zhejiang clip, aligning the existing Qwen transcript took
89.8 seconds and produced 25 timed sentences across 2 CAM++ speaker IDs.

This makes Qwen usable in the dubbing pipeline, with a large CPU-time cost.
The Whisper + CAM++ backend remains the default; select **Qwen 1.7B + timestamp
+ CAM++** in Settings to use the optional backend. Install its Python runtime
with `pip install -r requirements-qwen.txt`; the ASR and aligner weights total
about 6 GB and download on first use. The backend falls back to FunASR and
marks its output for review if Qwen or alignment fails.

### Sources

- [Zhejiang school report on China News](https://www.chinanews.com/sh/shipin/cns/2019/04-13/news811530.shtml) — includes the interview script.
- [Zhejiang school video on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:2019-04-13_%E6%B5%99%E6%B1%9F%E4%B8%80%E5%B0%8F%E5%AD%A6%E5%AD%A6%E7%94%9F%E8%A1%A8%E7%8E%B0%E5%A5%BD%E8%83%BD%E5%92%8C%E6%A0%A1%E9%95%BF%E4%B8%80%E8%B5%B7%E5%90%83%E9%A5%AD_%E6%A0%A1%E9%95%BF%E7%A7%B0%E4%B8%8D%E6%80%95%E4%BA%89%E8%AE%AE.webm).
- [Ma Jian VOA interview on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ma_Jian_VOA_interview_20181112.webm).
- [Bean farms in Danba County on Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Bean_farms_in_Danba_County,_Ngawa,_Sichuan.webm) — describes the local speakers, dialects, and interview timestamps.
