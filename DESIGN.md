# VietDub — Tài liệu thiết kế chi tiết

- Phiên bản: 0.1 — 2026-10-08
- Trạng thái: chờ Tony duyệt, chưa code
- Nguyên tắc: tham khảo workflow pyVideoTrans. Tony chốt 2026-10-08: VietDub mang license **GPL-3.0** → được phép port/adapt trực tiếp code pyVideoTrans. File `LICENSE` trong repo là GPL-3.0 nguyên văn. Mọi file có dùng code/adapt từ pyVideoTrans phải giữ credit + copyright của tác giả gốc (jianchang512/pyvideotrans) trong header. Code VietDub viết mới cũng thuộc GPL-3.0.

## 1. Tổng quan

VietDub là app desktop (PySide6) chạy trên Windows 11, lồng tiếng video tiếng Trung sang tiếng Việt:

- Nghe + tách loa tự động (FunASR, chạy local, CPU).
- Đoán giới tính từng loa bằng pitch → gán giọng lồng tiếng nam/nữ.
- LLM phân tích quan hệ người nói trước khi dịch → đại từ xưng hô chuẩn (tôi/em/anh/ngài…).
- Lồng tiếng bằng Edge-TTS (2 giọng Việt: 1 nam + 1 nữ), tự co giãn tốc độ cho khớp thời lượng từng câu.
- Trộn tiếng lồng lên trên tiếng gốc (giảm nhỏ), gắn phụ đề, xuất video hoàn chỉnh.
- Có điểm dừng duyệt tay sau bước nghe và sau bước dịch.
- Module dịch cắm được 2 nguồn: 9Router (mimo-v2.6-flash-free, mặc định) và Ollama local.

Mục tiêu phi chức năng: chạy được trên máy CPU 16GB RAM, không cần GPU, toàn bộ miễn phí, project lưu được giữa chừng để chạy tiếp.

**Tiêu chuẩn production (Tony 2026-10-08 — "Đây không phải app demo, nó phải là app dùng thật"):**
- Không code đối phó, không UI giả, không logic placeholder, không nút bấm chết — mọi chức năng chạy thật end-to-end: tải link thật, ASR thật, dịch thật, TTS thật, render ra video thật xem được.
- Lỗi báo bằng tiếng Việt dễ hiểu, kèm cách khắc phục cụ thể (vd: thiếu model → nút/hướng dẫn tải; Ollama chưa chạy → lệnh `ollama pull`).
- Settings lưu lại giữa các lần mở app (`%APPDATA%/VietDub/settings.json`), mở lại là đúng lựa chọn cũ.
- File .exe đóng gói: Tony tải về bấm chạy được ngay trên Windows, không cần cài Python — kèm hướng dẫn ngắn trong README.

## 2. Pipeline chi tiết (9 bước)

```
Video đầu vào (file local HOẶC link Douyin/TikTok/YouTube...)
        │
        ▼
[0] Lấy video ── yt-dlp (nếu là link) → tải mp4 tốt nhất về thư mục project
        │   (file local → bỏ qua bước này)
        ▼
[1] Tách audio ── ffmpeg → wav 16kHz mono
        │
        ▼
[2] Nghe + tách loa ── FunASR (SeacoParaformer + fsmn-vad + cam++)
        │   → segments: {index, start, end, speaker, text_src}
        │   ⏸ ĐIỂM DỪNG DUYỆT #1: sửa chữ, gộp/tách câu, sửa loa
        ▼
[3] Đoán giới tính từng loa ── pitch (librosa/pyin)
        │   → speaker: {id, gender: male/female, confidence}
        │   (sửa tay ở màn duyệt #1 nếu đoán sai)
        ▼
[4] LLM phân tích quan hệ ── provider dịch đã chọn
        │   → speakers: [{id, gender, vai_trò, nói_với_ai, đại_từ}]
        ▼
[5] Dịch sang tiếng Việt ── cùng provider, prompt có quan hệ + giới tính
        │   → segments: thêm text_vi
        │   ⏸ ĐIỂM DỪNG DUYỆT #2: sửa bản dịch
        ▼
[6] Lồng tiếng ── Edge-TTS
        │   → loa nữ: vi-VN-HoaiMyNeural, loa nam: vi-VN-NamMinhNeural
        │   → wav từng câu, atempo co giãn khớp timestamp (giới hạn 0.8–1.25)
        ▼
[7] Trộn audio ── tiếng lồng 100%, tiếng gốc giảm còn ~15% (config được)
        │
        ▼
[8] Ghép video ── ffmpeg: mux audio mới + phụ đề (gắn cứng hoặc .srt rời)
        │
        ▼
Video đầu ra (tenvideo_vidub.mp4) + file .srt
```

Fallback từng bước:

| Bước | Lỗi | Dự phòng |
|------|-----|----------|
| [0] Lấy video | link sai / cần đăng nhập / bị chặn | báo lỗi tiếng Việt dễ hiểu, retry 2 lần → gợi ý tải tay file rồi kéo vào tab File |
| [2] ASR | OOM / model lỗi | tự đổi sang model nhẹ hơn, báo log |
| [4–5] Dịch | 9Router timeout/503 | thử lại 3 lần → đổi sang Ollama nếu có → Google Translate free (cảnh báo có thể 429) |
| [6] TTS | Edge-TTS websocket lỗi | gTTS (giọng đơn, báo rõ trong log) |
| [8] Render | thiếu font sub | dùng font hệ thống, báo log |

## 3. Kiến trúc thư mục

```
vietdub/
├── core/
│   ├── orchestrator.py     # chạy 9 bước theo thứ tự, phát signal tiến trình
│   ├── job.py              # trạng thái job: idle/running/paused/review/done/failed
│   └── checkpoint.py       # lưu/khôi phục sau mỗi bước
├── asr/
│   └── funasr_adapter.py   # load model 1 lần, transcribe + speaker labels
├── speaker/
│   └── gender.py           # pitch (pyin) → male/female + confidence
├── translation/
│   ├── base.py             # interface chung: analyze() + translate()
│   ├── nine_router.py      # gọi 9Router / mimo-v2.6-flash-free
│   ├── ollama.py           # gọi Ollama local
│   └── prompts.py          # prompt phân tích quan hệ + prompt dịch
├── tts/
│   ├── edge_tts.py         # 2 giọng nam/nữ, rate/pitch config
│   └── duration_fit.py     # đo wav → atempo khớp timestamp
├── media/
│   ├── extract.py          # ffmpeg tách audio
│   ├── mix.py              # trộn dub + original (ducking)
│   ├── render.py           # mux + phụ đề
│   └── subs.py             # đọc/ghi srt, style
├── project/
│   ├── schema.py           # Segment, Speaker, Project (dataclass)
│   └── io.py               # lưu/đọc project.json, stages/*.json
├── ui/                     # PySide6
│   ├── main_window.py      # màn hình chính
│   ├── progress.py         # màn đang xử lý (QThread + signal)
│   ├── review_source.py    # duyệt sub gốc
│   ├── review_vi.py        # duyệt bản dịch
│   ├── finish.py           # hoàn thành + xem thử
│   └── settings_dialog.py  # cài đặt
└── packaging/
    └── vietdub.spec        # PyInstaller
```

Nguyên tắc: `core/` không biết gì về UI — UI chỉ gọi orchestrator và nhận signal. Sau này đổi UI (web) không phải sửa lõi.

## 4. Data model

Segment (đơn vị nhỏ nhất, 1 câu nói):

```json
{
  "index": 0,
  "start": 0.0,
  "end": 4.2,
  "speaker": 0,
  "gender": "female",
  "audience": "audience",
  "text_src": "乌兰察布的风很大",
  "text_vi": "Gió ở Ô Lan Sát Bố lớn lắm",
  "audio_vi": "stages/tts/seg_000.wav"
}
```

`audience` (Tony 2026-10-09): id loa đang được nói tới (dạng chuỗi, vd `"1"`),
hoặc `"audience"` (khán giả chung), hoặc `"all"` (mọi người trong cảnh), hoặc
`""` (chưa xác định → dùng cặp default). Một người có thể nói với NHIỀU người
khác nhau trong cùng video (vd phóng viên vừa hỏi khách mời vừa quay ra nói
với khán giả) — vì vậy audience là thuộc tính của từng SEGMENT, không phải
của loa. Màn duyệt sub gốc có cột "Nói với ai" sửa được.

Speaker:

```json
{ "id": 0, "gender": "female", "confidence": 0.92,
  "role": "phóng viên", "tone": "formal",
  "relations": [
    { "audience": "audience", "pronoun_i": "tôi",
      "pronoun_you": "quý vị", "is_default": true },
    { "audience": "1", "pronoun_i": "tôi",
      "pronoun_you": "anh", "is_default": false }
  ],
  "pronoun_i": "tôi", "pronoun_you": "quý vị" }
```

Mỗi loa có DANH SÁCH quan hệ (một phần tử cho mỗi đối tượng khác nhau), đúng
1 cái đánh dấu `is_default` (dùng khi không xác định được audience của câu).
`pronoun_i`/`pronoun_you` cấp loa luôn sync với relation default (tương thích
ngược với checkpoint cũ). Bước [5] tra `(speaker, audience)` → cặp đại từ
đúng cho từng câu.

Project (`project.json`):

```json
{
  "name": "demo",
  "video_source": "file",
  "video_url": "",
  "video_in": "D:/videos/clip.mp4",
  "video_out": "D:/videos/clip_vidub.mp4",
  "src_lang": "zh", "dst_lang": "vi",
  "voice_male": "vi-VN-NamMinhNeural",
  "voice_female": "vi-VN-HoaiMyNeural",
  "dub_volume": 1.0, "orig_volume": 0.15,
  "sub_mode": "burn",
  "translate_provider": "9router",
  "review_stops": true,
  "stages_done": ["extract", "asr"]
}
```

Checkpoint: sau mỗi bước, `stages/<ten_buoc>.json` được ghi. Mở lại project → chạy tiếp từ bước chưa xong, không chạy lại từ đầu.

## 5. Module dịch chi tiết

### 5.1. Provider

Interface chung (`translation/base.py`): 2 hàm `analyze(segments, speakers)` và `translate(segments, analysis)`. Thêm provider mới chỉ cần implement 2 hàm này.

**9Router (mặc định):**
- Endpoint: `https://...` (cấu hình trong settings), model `mimo-v2.6-flash-free`.
- Đã test thực tế: dịch Trung→Việt chuẩn đại từ nhất trong 14 model free (您→"ngài", cấp trên→"em/anh"; phân tích đúng phóng viên→khán giả: tôi/quý vị).
- Cần API key của Tony, lưu trong settings (không hardcode).
- LƯU Ý RỦI RO (review 2026-10-08): hiện code dùng cơ chế bypass free-tier bằng header giả mạo OpenCode client (đã test hoạt động). Mong manh — 9Router vá lỗ hổng là bước dịch sập; có rủi ro ToS. Sáng Tony quyết: dùng API key chính thức làm đường chính, hay chấp nhận rủi ro bypass. Đêm nay giữ nguyên behavior.

**Ollama (local):**
- Endpoint mặc định `http://localhost:11434`, model do Tony chọn (ô nhập trong settings).
- Dùng chung prompt với 9Router. Chất lượng phụ thuộc model Tony kéo về — không cam kết bằng mimo.

### 5.2. Bước [4] — Phân tích quan hệ (3 tầng, Tony chốt 2026-10-09)

Không gửi toàn bộ subtitle 1 lần lên LLM (dễ lỗi với video dài) — chia 3 tầng:

**(a) Batch (~20 câu/batch):** mỗi batch LLM phân tích → bảng batch gồm:
- `segments`/`lines`: mỗi câu `{id, audience}` — câu này đang nói với ai
  (id loa | `"audience"` | `"all"`), dựa vào ngữ cảnh batch (câu trước của ai,
  có từ "quý vị/khán giả" không, có gọi tên không...).
- `speakers`: mỗi loa trong batch có `role`, `tone`, và `relations[]`
  (danh sách `{audience, pronoun_i, pronoun_you}`, 1 cái `is_default`).

**(b) Bảng tổng hợp:** gom tất cả bảng batch — mỗi loa 1 dòng: xuất hiện ở
batch nào, mỗi batch gán vai trò/đại từ gì, số câu nói của loa đó, highlight
rõ chỗ mâu thuẫn giữa các batch.

**(d) Metadata tổng thể (1 pass LLM riêng, chạy trước trọng tài):** lấy mẫu
DÀN ĐỀU 8–10 đoạn suốt video (mỗi đoạn ~10 câu; video ngắn <5 phút hoặc
<100 câu thì gửi toàn bộ), kèm bảng quan hệ gộp sơ bộ (majority) + phân bố
số câu theo loa → JSON `{genre, style, setting, tone_notes}` (vd
tin tức/trang trọng/hiện đại). Lưu vào `stages/analyze.json`; màn duyệt hiển
thị cho Tony xem/sửa, nút "Dịch lại với metadata này".

**(c) Trọng tài (1 pass LLM cuối):** gửi bảng tổng hợp + metadata tổng thể +
vài câu mẫu gây tranh cãi (câu gốc của loa mà các batch bất đồng) → chốt
BẢNG CHUNG KHÓA duy nhất: mỗi loa 1 `relations[]` cuối cùng. Rớt → gộp đa số
deterministic dự phòng (majority theo từng audience, default = audience được
đánh dấu nhiều nhất).

Bước [5] mọi batch dịch đều nhận bảng đã khóa này → đại từ nhất quán cả phim dài.

**Fix đại từ 2026-10-09** (video 01/06 thiếu cặp kỳ vọng): nguyên nhân gốc là
LLM lạm dụng fallback `tôi/bạn` cho người được phỏng vấn (3/3 runs) — lỗi ở
bước phân tích, không phải bước dịch. Đã sửa:
1. Prompt phân tích (tiếng Anh): rule phân tầng — tin tức/phỏng vấn:
   người dẫn→khán giả `tôi/quý vị`; người được phỏng vấn/khách→phóng viên:
   `tôi/anh` (quy ước lồng tiếng, sửa được ở màn duyệt); cấm dùng "bạn" làm
   lối thoát lười trong ngữ cảnh trang trọng; `tôi/bạn` chỉ cho bạn bè thân
   mật rõ ràng. Mỗi câu xác định audience riêng.
2. `translation/base.py::_post_rule_interviewee`: quy tắc hậu kiểm
   deterministic (có log) — chương trình tin tức (có người dẫn với relation
   audience = `tôi/quý vị`) mà speaker nào rớt về đúng cặp fallback `tôi/bạn`
   ở relation default và không phải người dẫn → sửa default
   `pronoun_you="anh"`.
3. Audience từng câu được persist vào checkpoint `asr` (analyze chỉ điền chỗ
   còn trống — tôn trọng cột "Nói với ai" Tony sửa tay ở màn duyệt #1).

System prompt phân tích (tiếng Anh — Tony chốt 2026-10-08, format relations
từ 2026-10-09):

```
You are a dialogue analyst for videos. Task: read a transcribed dialogue
already split by speaker (SPEAKER_0, SPEAKER_1, ...) with each speaker's
gender, and determine for each line WHO it is addressed to, plus each
speaker's pronoun tables per audience.

A speaker may address DIFFERENT audiences in different lines (e.g. a reporter
may question a guest in one line and turn to the viewers in the next).

Return ONLY a valid JSON object, no other text:
{
  "speakers": [
    { "id": 0,
      "role": "the person's role (e.g. young reporter)",
      "tone": "formal | friendly | neutral",
      "relations": [
        { "audience": "audience | all | <speaker id as string>",
          "pronoun_i": "first-person pronoun in Vietnamese WITH diacritics",
          "pronoun_you": "address pronoun in Vietnamese WITH diacritics",
          "is_default": true } ] }
  ],
  "lines": [
    { "id": 0, "audience": "audience" },
    { "id": 5, "audience": "1" } ]
}

Rules for audience per line:
- The line mentions "quý vị", "khán giả", "mọi người", or speaks to viewers -> "audience".
- A question, answer, or reply continuing the previous speaker's line -> that previous speaker's id.
- The line calls someone by name/title matching another speaker's role -> that speaker's id.
- Plain narration / statement of facts with no addressee -> "audience".
- When truly unclear -> "audience".

Rules for relations (one entry per distinct audience of that speaker; mark the most frequent audience as is_default):
- News anchor / reporter / narrator -> audience: "tôi" / "quý vị".
- Interviewee / guest / attendee -> reporter: "tôi" / "anh". This is the conventional Vietnamese dubbing default for Chinese news programs; the user can correct it at review.
- Young reporter interviewing an older official in a NON-news chat setting -> reporter says "em", calls them "anh"/"chị".
- Married couple -> "anh"/"em". Close friends, classmates, peers chatting informally -> "tớ"/"cậu" or "tôi"/"bạn".
- Do NOT use "tôi"/"bạn" as a lazy default in news, interview, or formal settings. Only use it when the speakers are clearly informal peers.
- If truly nothing can be determined -> "tôi" / "bạn".
```

Prompt trọng tài (tiếng Anh, JSON only): "bạn là trọng tài, dựa vào bảng tổng
hợp + metadata + câu mẫu tranh cãi để chốt bảng quan hệ chung duy nhất, giải
thích ngắn gọn (note) khi có mâu thuẫn". Chi tiết đầy đủ trong
`translation/prompts.py::ARBITER_SYSTEM`.

### 5.3. Bước [5] — Dịch

Mỗi batch ~20 câu. Mỗi batch kèm 2 câu trước đó làm overlap context NHƯNG đặt
trong section riêng "CONTEXT ONLY — do NOT translate" (fix 2026-10-09: trước
đây trộn chung khiến LLM dịch luôn cả câu context, trả thừa id → tốn retry).
Prompt mỗi batch gồm:
1. **VIDEO CONTEXT** (metadata từ bước [4]: thể loại/phong cách/bối cảnh/giọng
   điệu) + chỉ dẫn chọn từ ngữ/đại từ phù hợp thể loại (vd cổ trang →
   "tại hạ/các hạ", tin tức → trang trọng, hoạt hình → hồn nhiên).
2. Bảng quan hệ ĐÃ KHÓA: mỗi loa liệt kê `to '<audience>': pronoun_i/pronoun_you`
   (+ đánh dấu default).
3. Danh sách câu: `[id] SPEAKER_x (to SPEAKER_y | to AUDIENCE | to ALL): text`.

Từng câu tra `(speaker, audience)` → cặp đại từ đúng cho câu đó; không có
trong bảng → dùng cặp default của loa. Temperature 0.1–0.3, validate JSON +
retry nếu sai format.

**Validate sau dịch** (Tony): số câu ra phải == số câu vào (thiếu → dịch lẻ
từng câu bù); câu nào rớt đại từ so với bảng khóa thì đánh dấu `needs_review`
(kiểm tra theo nhóm `(speaker, audience)` ≥3 câu, hiện vàng ở màn duyệt #2
cho Tony duyệt tay).

System prompt (tiếng Anh — Tony chốt 2026-10-08, cập nhật relations 2026-10-09):

```
You are a professional dubbing translator translating video dialogue from
Chinese to Vietnamese.

You receive: (1) VIDEO CONTEXT (genre/style, may be absent), (2) a speaker-
relationship table with locked pronouns per (speaker, audience) pair - a
speaker may have SEVERAL pairs, (3) a list of lines: id, speaker -> audience,
start/end time, Chinese text.

Requirements:
- For EACH line, look up its (speaker, audience) pair in the relationship
  table and use EXACTLY those pronouns for that line. Different lines of the
  same speaker may need different pronouns.
- If a line's (speaker, audience) pair is not in the table, use the pair
  marked [default] for that speaker.
- Translate naturally, as spoken Vietnamese - short, fluent lines easy to
  read aloud.
- Keep the exact number of lines and their ids - do NOT merge, split, or drop
  lines.
- No commentary, no explanations.

Return ONLY valid JSON: { "translations": [ { "id": 0, "text_vi": "..." } ] }
```

Output: `text_vi` cho từng segment, giữ nguyên index/start/end.

## 6. Module TTS chi tiết

- Thư viện: `edge-tts` (Python). Giọng mặc định: nữ `vi-VN-HoaiMyNeural`, nam `vi-VN-NamMinhNeural` — cả 2 đều có sẵn, miễn phí, không cần key.
- Config: `rate` (tốc độ, vd +0%/−10%), `pitch` (cao/thấp giọng).
- Có nút "Nghe thử" trong settings: nhập câu mẫu → phát thử 2 giọng.
  - GHI CHÚ (chốt 2026-10-09, giải quyết mâu thuẫn với mục 8): nút [Nghe thử]
    giọng nam/nữ đặt ở **màn hình chính** (ngay cạnh dropdown chọn giọng,
    đúng mục 8), KHÔNG lặp lại trong dialog Cài đặt. Màn chính là nơi user
    chọn giọng nên nghe thử tại chỗ là hợp lý nhất; dialog Cài đặt chỉ giữ
    các tham số giọng (rate/pitch/âm lượng).
- Khớp thời lượng (`tts/duration_fit.py`):
  1. Sinh wav từng câu, đo độ dài thật.
  2. Tỉ lệ = dài_wav / (end − start). Dùng ffmpeg `atempo` co giãn, giới hạn 0.8–1.25 (ngoài ngưỡng nghe sẽ méo).
  3. Nếu tỉ lệ vượt ngưỡng: ưu tiên ngắt câu dài thành 2 câu con ở dấu phẩy/chấm (chạy lại TTS), không cố kéo giãn quá đà.
- Lưu ý đã biết: websocket của Edge-TTS bị chặn trong sandbox của Milo → bước này verify cuối trên máy Windows của Tony.

## 7. Module media chi tiết

- `[1] extract`: `ffmpeg -i in.mp4 -vn -ar 16000 -ac 1 audio.wav` (đúng format FunASR cần).
- `[3] gender`: đọc wav bằng librosa, pitch trung vị mỗi loa bằng pyin. Ngưỡng mặc định: <160Hz → nam, >160Hz → nữ, kèm confidence. Ngưỡng config được.
- `[7] mix`: track dub giữ 100%, track gốc giảm còn 15% (config `orig_volume`, có thể 0 = tắt hẳn). Căn thời gian bằng `adelay` theo start từng câu.
- `[8] render`:
  - Video: copy stream gốc nếu được (nhanh), encode lại `libx264 crf 20` khi cần gắn cứng sub.
  - Phụ đề: 2 chế độ — `burn` (gắn cứng bằng filter subtitles, font/cỡ/màu/vị trí config) hoặc `srt` (xuất file rời cùng tên).
  - Output: `<tên_gốc>_vidub.mp4` trong thư mục Tony chọn.

## 8. UI PySide6 chi tiết

Chạy pipeline trong `QThread`, UI nhận signal `progress(step, pct, msg)` và `log(line)` — không bao giờ block giao diện.

**Màn 1 — Chính:** 2 tab "File" / "Link". Tab File: kéo-thả/chọn video → hiện info (tên, thời lượng, phân giải). Tab Link: ô paste link (Douyin/TikTok/YouTube...) + nút [Tải về] hiện tiến trình (% + tốc độ) → tải xong hiện info video như tab File, lúc đó mới cho [Bắt đầu]. Chọn nhanh: giọng nam, giọng nữ (dropdown + nút nghe thử), nguồn dịch (9Router/Ollama), tick "dừng duyệt sau mỗi chặng" (mặc định bật), tick "chế độ qua đêm" (bật → tự tắt dừng duyệt), thư mục lưu. Nút [Bắt đầu] → Màn 2.

**Màn 2 — Đang xử lý:** thanh tiến trình 9 bước (tên bước hiện tại + %), log realtime cuộn được, nút [Tạm dừng] [Hủy]. Tới điểm dừng duyệt → tự mở Màn 3/4.

**Màn 3 — Duyệt sub gốc:** bảng # | bắt đầu | kết thúc | loa | giới tính (dropdown sửa) | nói với ai (dropdown: chưa rõ/khán giả/tất cả/loa N — bước [4] chỉ điền chỗ còn trống, tôn trọng sửa tay) | nội dung (sửa trực tiếp, Enter xuống dòng). Nút [Nghe lại câu] (phát đoạn audio gốc của câu đang chọn). [Quay lại] [Tiếp tục dịch →].

**Màn 4 — Duyệt bản dịch:** bảng # | thời gian | loa | bản dịch (sửa trực tiếp). Form metadata video (thể loại/phong cách/bối cảnh/giọng điệu — LLM suy từ bước [4], sửa tay được) + nút [Dịch lại với metadata này]. Câu nào rớt đại từ so với bảng khóa (nguồn có đại từ nhân xưng mà bản dịch thiếu) được tô vàng.

**Màn 5 — Hoàn thành:** player xem thử video đã lồng tiếng + sub, nút [Mở thư mục] [Làm video khác].

**Dialog Cài đặt** (mở từ mọi màn): 9Router API key + model, Ollama endpoint + model, model ASR (lớn/nhỏ), model dấu câu, ngưỡng pitch, âm lượng dub/gốc, style phụ đề, chất lượng video, đường dẫn FFmpeg.

Quy tắc UI: không dùng emoji làm icon, icon vẽ tay/vector đồng bộ.

## 9. Config đầy đủ

**Cài đặt chung** (`%APPDATA%/VietDub/settings.json`): 9Router key/model, Ollama endpoint/model, model ASR + dấu câu, giọng nam/nữ mặc định, rate/pitch, ngưỡng pitch, âm lượng, style sub, crf, review_stops mặc định.

**Theo từng project** (lưu trong `project.json`): video vào/ra, cặp giọng, nguồn dịch, âm lượng, chế độ sub, có dừng duyệt hay không. Mở project cũ = khôi phục đúng lựa chọn lần trước.

## 10. Xử lý lỗi & chạy tiếp

- Sau mỗi bước ghi checkpoint `stages/<bước>.json`. Crash/mất điện → mở lại project → chạy tiếp từ bước dở, không làm lại từ đầu.
- Bước nào lỗi: thử lại tối đa 3 lần → fallback (bảng ở mục 2) → nếu vẫn lỗi: dừng, giữ nguyên checkpoint, log ghi rõ bước nào + lý do, UI hiện nút [Chạy tiếp từ bước lỗi].
- Hủy giữa chừng: giữ checkpoint tới bước đã xong.

## 10.5. Edge cases (Tony yêu cầu 2026-10-08 — "Edge case nhiều")

Mỗi case phải có cách xử lý trong code + test case tương ứng (chạy ở Wave 1/3). Research pyVideoTrans đang chạy song song — cách họ xử lý các case tương đương sẽ được đối chiếu và bổ sung vào đây.

| # | Edge case | Cách xử lý trong code | Test ở |
|---|-----------|----------------------|--------|
| 1 | Câu nói quá dài, TTS dài hơn timestamp | Đo tỉ lệ `dur_tts/(end-start)`. Nếu > 1.25: tự chia câu ở dấu phẩy/chấm gần giữa nhất, TTS lại từng câu con, chia timestamp theo tỉ lệ ký tự | Wave 1: unit `duration_fit` với câu dài giả lập |
| 2 | Câu quá ngắn (< 0.5s) | `atempo` tối thiểu 0.8, không nén dưới ngưỡng. Cho phép dub tràn nhẹ quá slot (đặt theo `start`), log warning | Wave 1: unit với segment 0.3s |
| 3 | Khoảng lặng dài giữa các câu | Dub đặt đúng `start` từng câu bằng `adelay`, không kéo dài lấp khoảng lặng — giữ im lặng nguyên | Wave 1: integration kiểm tra timeline output còn gap |
| 4 | Hai người nói chồng tiếng (overlap) | cam++ gán theo loa chiếm ưu thế; segment có 2 loa cùng lúc → log warning + `needs_review=true` | Wave 1: unit với segment overlap giả lập |
| 5 | Nhạc nền/tiếng ồn lớn | VAD lọc; segment nào confidence < ngưỡng → `needs_review=true`, nổi bật ở màn duyệt để Tony kiểm tra tay | Wave 1: unit flag confidence thấp |
| 6 | Video không có track audio / track lỗi | Bước [1] dùng ffprobe kiểm tra trước; không có audio → báo lỗi rõ ràng "video không có track audio", dừng sạch, không crash | Wave 1: chạy với video câm |
| 7 | LLM trả JSON sai format | Validate (json parse + schema). Retry tối đa 3 lần → vẫn sai → fallback: bỏ bước phân tích, dịch thẳng với đại từ mặc định (tôi/bạn) | Wave 1: mock LLM trả JSON hỏng |
| 8 | LLM tự gộp/tách/bỏ câu | Validate `len(translations) == len(segments)` và ids khớp. Sai → retry → 3 lần vẫn sai → fallback dịch thẳng | Wave 1: mock LLM trả thiếu câu |
| 9 | Tên riêng tiếng Trung (vd 乌兰察布) | Prompt dịch có quy tắc: giữ tên riêng, phiên âm Hán-Việt, không dịch nghĩa. Settings có danh sách tên riêng tùy chỉnh thêm | Wave 1: dịch câu có 乌兰察布, kiểm tra output giữ nguyên/phiên âm |
| 10 | Edge-TTS disconnect giữa chừng | Checkpoint theo từng câu (`stages/tts/seg_XXX.wav` + manifest). Chạy lại → tiếp tục từ câu dở, không TTS lại từ đầu | Wave 1: mock disconnect ở câu 5 rồi resume |
| 11 | Ký tự đặc biệt trong sub (nháy đơn, %) | Burn sub qua file .srt/.ass trung gian (không nhúng text trực tiếp vào filter args) để ffmpeg tự escape | Wave 1: sub chứa `'` và `%`, render thử không lỗi |
| 12 | Video có nhiều track audio | ffprobe liệt kê; mặc định lấy track 0; màn hình chính có dropdown chọn track khi phát hiện > 1 | Wave 1: unit parse ffprobe multi-track; Wave 2: kiểm tra dropdown hiện |
| 13 | Tên file có dấu/cách/ký tự đặc biệt | Gọi ffmpeg bằng list args qua `subprocess` (không `shell=True`), test path có dấu trên Windows | Wave 1: file tên có dấu + cách |
| 14 | Ollama chưa chạy / model chưa kéo | Health check `/api/tags` trước khi dịch; lỗi → báo dễ hiểu + hướng dẫn `ollama pull <model>` | Wave 1: mock endpoint chết |
| 15 | 9Router 503 / hết quota | Retry 3 lần (backoff) → chuyển Ollama (nếu đã cấu hình) → Google Translate free (log cảnh báo chất lượng đại từ có thể kém) | Wave 1: mock 9Router 503 |
| 16 | Checkpoint bị corrupt | Đọc checkpoint trong try/except + kiểm tra cấu trúc; hỏng → tự bỏ file hỏng, chạy lại từ bước trước đó, log rõ | Wave 1: ghi file checkpoint rác rồi resume |
| 17 | Video dài (phim 90 phút) | Xử lý theo chunk: ASR theo đoạn 5–10 phút, TTS theo câu; không ôm cả wav dài vào RAM. Ước lượng RAM đỉnh theo thời lượng, cảnh báo trước nếu vượt RAM máy | Wave 1: đo RAM trên clip 55s rồi ngoại suy; Wave 3: test với video dài hơn nếu có |
| 18 | Link tải video lỗi (cần đăng nhập / bị chặn / link sai) | yt-dlp báo lỗi → dịch sang tiếng Việt dễ hiểu (vd "link cần đăng nhập", "Douyin chặn IP này"), không crash. Retry 2 lần → vẫn lỗi → gợi ý anh tải tay file rồi kéo vào tab File | Wave 1: unit với link sai + mock lỗi 403 |

## 11. Đóng gói & cài đặt (máy Tony — Win 11, 16GB RAM)

- PyInstaller chế độ onedir → 1 thư mục `VietDub/`, chạy `VietDub.exe`, không cần cài Python.
- FFmpeg đóng gói kèm (binary Windows).
- Model FunASR tải 1 lần duy nhất lúc chạy đầu tiên về `%APPDATA%/VietDub/models/` (~1.3GB với ct-punc 290M — bản nhẹ, sẽ đo lại RAM trước khi chốt).
- Không cần GPU. RAM đỉnh đo được ~5.3GB với bản ct-punc-large → bản release dùng ct-punc 290M để nhẹ hơn.

## 12. Tiêu chí nghiệm thu (verify)

Tony nhấn mạnh 2026-10-08 23:03: "Test kĩ nhé". Không wave nào được coi là xong nếu chưa có bằng chứng (log/số đo/screenshot). Báo cáo mỗi wave phải có 2 mục: "đã test gì + bằng chứng" và "chưa test được gì + vì sao".

**Wave 1 — lõi pipeline:**
- Mỗi module có unit test độc lập.
- Test tích hợp trên clip thật 55s (`~/workspace/pyvideotrans-demo/work/man_clip/audio.wav`):
  - Tách loa phải ra 0 → 1 → 0, đối chiếu khớp file `~/workspace/pyvideotrans-demo/hidden_files/test_funasr_spk/funasr_paraformer_vad_campp_55s.json`.
  - Bản dịch test bằng 9Router/mimo-v2.6-flash-free phải giữ đúng đại từ như kết quả đã test trước đây.
  - Đo thời gian chạy + RAM đỉnh từng bước.
- Edge-TTS websocket bị chặn trong sandbox → test module tts bằng mock/unit, ghi rõ "chờ verify cuối trên máy Windows của Tony".

**Wave 2 — UI:**
- Screenshot TỪNG màn hình (5 màn + settings dialog).
- Kiểm tra 3 mức theo luật của Tony: (1) chỗ mới/sửa đã đúng chưa, (2) xung quanh có bị ảnh hưởng không, (3) cả màn hình có gì lạ không.
- Test luồng sửa ở màn duyệt (sửa chữ, sửa giới tính, sửa bản dịch) rồi chạy tiếp — checkpoint phải khớp với nội dung đã sửa.

**Wave 3 — đóng gói + end-to-end:**
- End-to-end Trung→Việt trên clip thật, đối chiếu từng tiêu chí dưới đây.
- **Test 20 video** (Tony 2026-10-08 — bằng chứng "app dùng thật"): 20 video đa dạng — độ dài từ vài chục giây đến vài phút, số người nói (1 / 2 / nhiều), có video nhạc nền ồn, có video lấy từ link (test bước tải), có file local, có video dọc/ngang. Mỗi video chạy pipeline đầy đủ (bỏ qua bước duyệt tay để chạy batch), ghi bảng: tên | độ dài | số loa tách được | giới tính đúng/sai | lỗi đại từ | TTS khớp giờ | lỗi gặp. Video nào fail → fix → chạy lại. Báo cáo cuối có bảng 20 video + tỉ lệ pass từng bước. Chuẩn bị video ở `hidden_files/test_videos/` + file `MANIFEST.md` ghi rõ nguồn từng video.
- PyInstaller build .exe cho Windows phải thành công không lỗi. Sandbox là Linux nên không chạy được .exe để verify cuối → ghi rõ trong báo cáo là bước chạy .exe trên Windows chờ Tony verify.

Chạy end-to-end trên clip test 55s (phóng viên + ông Lý):
- [ ] Tách loa đúng 0 → 1 → 0, biên thời gian lệch < 1s so với MOSS.
- [ ] Giới tính 2 loa đúng, đại từ bản dịch đúng quan hệ (phóng viên: tôi/quý vị; ông Lý: tôi/anh).
- [ ] Mỗi câu lồng tiếng lệch timestamp < 0.3s, không méo tiếng.
- [ ] Video xuất ra: nghe được tiếng Việt, tiếng gốc nhỏ nền, sub đúng giờ.
- [ ] Tắt app giữa bước [6], mở lại → chạy tiếp từ [6], không làm lại.

## 13. Task breakdown (đã duyệt)

**Wave 1 — lõi pipeline:** 1. khung project + checkpoint → 2. media (ffmpeg) → 3. asr (FunASR) → 4. speaker (pitch) → 5. translation (9Router + Ollama) → 6. tts (Edge-TTS 2 giọng + khớp giờ).

**Wave 2 — UI PySide6:** 7. màn chính → 8. màn xử lý → 9. duyệt sub gốc + duyệt dịch → 10. hoàn thành + settings.

**Wave 3 — đóng gói + test:** 11. PyInstaller .exe → 12. test end-to-end theo mục 12.

## Future: batch queue (Tony dặn 2026-10-08 — KHÔNG code trong 3 wave hiện tại)

Ý tưởng: hàng đợi chạy nhiều video lần lượt tự động (xếp N video, đi ngủ, sáng dậy có N video đã lồng tiếng).

Yêu cầu kiến trúc ngay từ bây giờ (để sau này không phải đập đi làm lại):

- **Tách khái niệm Job khỏi Project.** Job = 1 video + config + trạng thái (idle/running/paused/review/done/failed), hoàn toàn độc lập. Project hiện tại = 1 job; sau này Project có thể là container chứa nhiều job.
- **Orchestrator chỉ nhận 1 job**, không biết gì về hàng đợi — chạy xong job thì trả kết quả, ai gọi tiếp là việc của tầng trên.
- **Checkpoint theo từng job**: mỗi job có thư mục riêng (`jobs/<job_id>/stages/...`), không dùng chung state — job này crash không ảnh hưởng job khác.
- **BatchQueue (làm sau)**: module mới giữ danh sách job, chạy tuần tự từng job qua orchestrator, mỗi job checkpoint riêng, khi xong hết xuất báo cáo tổng (mấy job xong, mấy job lỗi + lý do).
- **UI màn hình chính (làm sau)**: chỉ cần thêm panel danh sách job (thêm video vào hàng đợi, xóa, sắp xếp thứ tự, xem trạng thái từng job) — lõi pipeline không phải sửa.

Hiện tại 3 wave chỉ làm 1 job / 1 lần chạy, nhưng code theo đúng tách bạch trên để sau này gắn BatchQueue vào là chạy.

## Chế độ chạy qua đêm (Tony 2026-10-08 — "Cắm máy sáng ra có 1 bộ phim")

Mục tiêu: 1 nút bấm → xử lý 1 phim ~90 phút trong ~8 tiếng qua đêm, sáng dậy có phim xem, không cần canh máy.

1. **Chế độ "Qua đêm"**: 1 nút trên màn hình chính. Bật chế độ này → `review_stops` TỰ TẮT (cấm treo chờ người giữa đêm — nếu bật review stops mà chạy qua đêm thì máy treo chờ, không được phép). Chạy liền 9 bước không dừng.
2. **Chạy không giám sát**: mọi lỗi tự retry + fallback theo chuỗi đã định (mục 2, 10.5); tuyệt đối KHÔNG hiện dialog chặn giữa chừng; log đầy đủ ra file theo từng job (`jobs/<job_id>/run.log`) để sáng ra đọc lại được chuyện gì đã xảy ra.
3. **Crash/mất điện giữa đêm**: checkpoint từng bước + từng câu TTS (10.5 case 10, 16) → mở lại app tự đề xuất "chạy tiếp từ chỗ dở".
4. **Đo và chứng minh vừa 1 đêm**: đo thời gian từng bước trên clip 55s, ngoại suy cho phim 90 phút. Nếu bước nào quá chậm → tối ưu (batch translation lớn hơn, TTS song song có giới hạn...). Bảng dưới ĐÃ ĐIỀN SỐ THẬT ở Wave 3 (2026-10-09) — cột "Nguồn số" ghi rõ số nào ĐO THẬT, số nào ƯỚC LƯỢNG:

| Bước | Đo trên clip 55s | Ngoại suy phim 90 phút (5400s, hệ số ×98.2) | Nguồn số | Ghi chú |
|------|------------------|----------------------------------------------|----------|---------|
| [0] Lấy video (link) | chưa đo | ~5–15 phút | ƯỚC LƯỢNG | tùy mạng; file local bỏ qua |
| [1] Tách audio | 0.2s | ~0.5–1 phút | ĐO THẬT → ngoại suy tuyến tính | ffmpeg, nhanh |
| [2] ASR + tách loa | 87.3s (RTF 1.59) | ~143 phút ≈ 2.4 tiếng | ĐO THẬT → ngoại suy tuyến tính | CPU; **nút thắt cổ chai** |
| [3] Pitch giới tính | 4.5s | ~7–8 phút | ĐO THẬT → ngoại suy tuyến tính | nhẹ |
| [4] LLM phân tích | gộp trong 42.9s của [4+5] | ~3–5 phút | ƯỚC LƯỢNG (1 batch/phim) | 1 lần / phim |
| [5] Dịch | 42.9s / 17 câu ≈ 2.5s/câu | ~40–45 phút (giả định ~1000 câu) | ĐO THẬT (tốc độ/câu) → ngoại suy | batch 20 câu/call |
| [6] TTS | chưa đo (sandbox chặn websocket) | ~3–4 phút | ƯỚC LƯỢNG: ~1000 câu × ~2s/câu ÷ concurrency 10 | chờ đo thật trên máy Tony |
| [7] Trộn audio | chưa đo | ~2–3 phút | ƯỚC LƯỢNG | ffmpeg |
| [8] Ghép video | chưa đo | ~5–10 phút | ƯỚC LƯỢNG | copy stream khi được |
| **Tổng** | | **~3.5–4 tiếng < 8 tiếng** | | **vừa 1 đêm** |

Số đo thật lấy từ `hidden_files/wave1_integration.log` (run 2026-10-08 16:58:15,
clip 55s: [1]=0.2s, [2]=87.3s, [3]=4.5s, [4+5]=42.9s).

LƯU Ý TRUNG THỰC về [2]: số đo trực tiếp pipeline FunASR thô trước đây là
16.8s/55s (RTF 0.305 → ngoại suy ~28 phút), nhưng đo qua `FunASRAdapter`
(modelscope pipeline: VAD + punc + cam++ trên CPU) là 87.3s (RTF 1.59 →
~143 phút). Bảng trên dùng số đo qua adapter (đúng code app chạy thật).
[2] chiếm ~2/3 tổng thời gian — nếu Tony muốn rút ngắn đêm chạy, hướng tối ưu:
giảm chunk ASR, batch VAD lớn hơn, hoặc thử bản paraformer nhỏ hơn.

5. **RAM cho audio 90 phút**: xử lý theo chunk (ASR theo đoạn 5–10 phút, TTS theo câu), không ôm hết vào RAM; báo RAM đỉnh ước lượng, cảnh báo trước nếu vượt RAM máy.
6. **Kết hợp batch queue (future)**: qua đêm chạy được NHIỀU phim nối tiếp nhau — mỗi job checkpoint riêng, job này lỗi không chặn job sau (log lỗi, chạy tiếp job kế).
