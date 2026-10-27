# Kiến trúc VietDub

**Nguồn trạng thái:** code hiện hành trong repository
**Rà soát:** 2026-10-27

## 1. Bối cảnh hệ thống

VietDub là desktop app xử lý video trên máy người dùng. Media và model ASR được xử lý local sau khi model có trong cache. Các ranh giới mạng gồm model download, URL video, nhà cung cấp dịch/LLM, Microsoft Edge-TTS và tùy chọn VietDub STT service trên loopback.

~~~mermaid
flowchart LR
    Human[Người dùng] --> Desktop[PySide6 UI]
    Desktop --> Runner[JobRunner / QThread]
    Runner --> Orch[Orchestrator<br/>một Job]
    Orch --> Domain[Project, Segment, Speaker]
    Orch --> Persistence[JobStore + checkpoints + logger]
    Orch --> ASR[ASR adapter]
    Orch --> Translation[Translation adapters]
    Orch --> TTS[Edge-TTS adapter]
    Orch --> Media[FFmpeg media modules]
    ASR --> Models[Whisper / FunASR / Qwen<br/>model cache]
    ASR -. optional HTTP .-> LocalSTT[VietDub STT service<br/>127.0.0.1:8768]
    Translation --> LLM[OpenAI-compatible API<br/>9Router / Ollama]
    Translation --> Google[Google Translate fallback]
    TTS --> Edge[Microsoft Edge-TTS]
    Media --> Result[MP4 + SRT]
    QueueStore[QueueStore] <--> QueueUI[BatchQueueWindow]
    JobStore <--> HistoryUI[JobHistoryDialog]
    QueueUI --> Desktop
    HistoryUI --> Desktop
~~~

## 2. Thành phần và trách nhiệm

| Thành phần | Module tiêu biểu | Trách nhiệm |
|---|---|---|
| Entry/theme | main.py, ui/theme.py | Tạo QApplication, nạp Settings, áp dụng theme, mở MainWindow |
| Source UI | ui/main_window.py | Chọn video file/URL, đọc metadata, chọn audio track, tạo Job và mở settings/history/queue |
| Worker UI | ui/progress.py | Chạy Orchestrator trong worker, hiển thị tiến độ/log, pause/cancel/retry và điều hướng review |
| Review UI | ui/review_source.py, ui/review_vi.py | Sửa transcript, người nói/giới tính, đối tượng xưng hô và bản dịch |
| History/queue UI | ui/job_history.py, ui/batch_queue.py | Lịch sử job, phục hồi queue và điều phối tuần tự |
| Core orchestration | core/orchestrator.py | Chạy một Job qua chín stage, resume, checkpoint và trạng thái cuối |
| Domain/persistence | project/schema.py, project/io.py, core/job*.py, core/checkpoint.py | Project, Segment, Speaker, snapshot, checkpoint, job metadata và source validation |
| ASR/speaker | asr/*, speaker/gender.py | Transcript, timestamp, diarization, confidence và pitch-based gender |
| Translation | translation/* | Phân tích quan hệ, metadata video, dịch theo batch, xác thực model output và fallback |
| TTS | tts/edge_tts.py, tts/duration_fit.py | Tổng hợp từng câu, fit thời lượng và lắp track theo timeline |
| Media | media/fetch.py, extract.py, mix.py, render.py, editor.py | Download, extract, mix, render, subtitle và editor export |
| Finish/editor | ui/finish.py, ui/editor.py | Preview thành phẩm, thao tác file và biên tập hậu kỳ |

Core không phụ thuộc Qt và không mở dialog. UI quản lý nhiều Job; mỗi lần gọi Orchestrator chỉ truyền đúng một Job.

## 3. Pipeline

~~~mermaid
flowchart TD
    Input[File hoặc URL] --> Fetch[0 Fetch<br/>URL tải vào job; file dùng trực tiếp]
    Fetch --> Extract[1 Extract<br/>FFmpeg → 16 kHz mono WAV]
    Extract --> ASR[2 ASR<br/>text + timestamp + speaker]
    ASR --> ReviewSource{Dừng duyệt transcript?}
    ReviewSource -->|Có| SaveSource[Persist source_review + review intent]
    SaveSource --> Gender[3 Gender estimate<br/>giữ nhãn người dùng]
    ReviewSource -->|Không| Gender
    Gender --> Analyze[4 LLM phân tích quan hệ]
    Analyze --> Translate[5 Dịch sang tiếng Việt]
    Translate --> ReviewVI{Dừng duyệt bản dịch?}
    ReviewVI -->|Có| SaveVI[Persist translate + review intent]
    SaveVI --> TTS[6 Edge-TTS từng câu]
    ReviewVI -->|Không| TTS
    TTS --> Fit[Khớp thời lượng<br/>co giãn hoặc tách câu]
    Fit --> Mix[7 Mix dub + tiếng gốc giảm nhỏ]
    Mix --> Render[8 Render MP4 + subtitle]
~~~

| Bước | Đầu vào chính | Kết quả bền vững |
|---|---|---|
| Fetch | file path hoặc URL | stages/fetch.json; URL có source.mp4 trong job |
| Extract | video + audio_track | stages/extract.json và audio.wav |
| ASR | audio WAV, backend, proper nouns | stages/asr.json gồm Segment |
| Gender | ASR segments + audio | stages/gender.json; gender cũng gắn lên segments |
| Analyze | segments + speakers | stages/analyze.json gồm relation và metadata video |
| Translate | segments + speakers + metadata | stages/translate.json |
| TTS | text_vi + speaker gender + giọng | stages/tts.json, tts_meta.json, audio từng câu và dub_track.wav |
| Mix | dub_track + extracted audio | stages/mix.json và mixed.wav |
| Render | video + mixed.wav + SRT/style | stages/render.json, output MP4 và SRT nếu dùng chế độ SRT |

Mỗi stage ghi checkpoint riêng. Artifact bắt buộc được kiểm tra trước khi checkpoint được dùng lại. Khi chạy lại từ stage cũ, stage đó và mọi kết quả phụ thuộc phía sau sẽ bị vô hiệu hóa.

## 4. Adapter và dịch vụ

### ASR

| Backend | Transcript/timestamp | Nhãn người nói | Ghi chú |
|---|---|---|---|
| Whisper large-v3-turbo | Whisper text và timestamps | CAM++/FunASR turns ghép theo overlap | Backend mặc định |
| FunASR | FunASR segments | CAM++ | SenseVoiceSmall, VAD và punctuation theo settings |
| Qwen3-ASR-1.7B | Qwen transcript + Qwen ForcedAligner | CAM++ | Cài requirements-qwen.txt; CPU dùng bfloat16 |
| VietDub STT | JSON contract từ local service | CAM++ trong app | Experimental; service thuộc package ngoài repo |

ASR tạo danh sách Segment. Segment giữ index, start/end giây, speaker ID, text gốc, confidence, cờ needs_review và audience; sau dịch có thêm text_vi. Câu confidence thấp được đánh dấu để review. Gender estimator dùng pitch; nhãn male/female nhập tay được ưu tiên khi chạy lại gender.

Model local chỉ tải khi stage ASR dùng backend đó. Cache mặc định ở thư mục models cạnh settings; HF_HOME và MODELSCOPE_CACHE do user đặt được tôn trọng.

### Phân tích và dịch

Settings hỗ trợ OpenAI API, 9Router và Ollama. Provider job chọn là đầu tiên; các provider đã cấu hình khác được thử tiếp khi provider trước lỗi. Khi tất cả LLM provider thất bại, translate_with_fallback có thể gọi Google Translate miễn phí làm fallback cuối. Chất lượng quan hệ/xưng hô thấp hơn pipeline LLM đầy đủ và dòng cần kiểm tra vẫn được đánh dấu.

Analyze phân batch transcript, tổng hợp quan hệ người nói, metadata video rồi khóa bảng quan hệ/đại từ. Translate dùng bảng quan hệ đó giữa các batch để giữ xưng hô nhất quán. Model output được parse/validate và retry khi JSON/segment IDs không hợp lệ.

### TTS và media

Pipeline hiện dùng Edge-TTS cho giọng tiếng Việt. Mặc định NamMinh cho male và HoaiMy cho female. Audio được lưu từng câu trong thư mục job. Câu dài được co giãn trong giới hạn cấu hình hoặc tách câu rồi tổng hợp lại. Nếu câu quá ngắn hoặc không thể chia, pipeline có thể nén tối đa và cho tràn nhẹ; lỗi không thể xử lý dừng job với hướng dẫn sửa câu.

Track dub được đặt theo timestamp với khoảng lặng giữa câu. Mix mặc định dub volume 1.0, tiếng gốc 0.15. Render hỗ trợ phụ đề burn-in hoặc SRT sidecar. FFmpeg ghi tệp tạm, sau đó publish không ghi đè và chọn hậu tố số tiếp theo khi tên đã tồn tại.

## 5. Domain, state và persistence

- **Project** là snapshot theo video: source, audio track, ngôn ngữ, voices, provider dịch, subtitle mode, review/overnight và các stage đã xong.
- **JobRecord** là lifecycle metadata có schema version, ID, timestamps, status, resume stage, last stage, progress, source identity và last error.
- **Checkpoint** là stage JSON độc lập; project.json giữ cấu hình tương thích với job cũ.
- **QueueManifest** giữ thứ tự entry, stable ID, queued/done/skipped, active entry và job ID liên kết.
- **Segment** là một câu thoại; **Speaker** giữ gender, role, relation, đại từ và tone.
- **Editor draft** nằm trong stages/editor.json; thao tác editor không ghi đè checkpoint pipeline.

~~~text
VietDub user data/
├── active_queue.json
└── jobs/
    └── <job-id>/
        ├── project.json
        ├── job.json
        ├── run.log
        ├── source.mp4             # chỉ với URL source
        └── stages/
            ├── fetch.json
            ├── extract.json
            ├── audio.wav
            ├── asr.json
            ├── source_review.json
            ├── gender.json
            ├── analyze.json
            ├── translate.json
            ├── review.json
            ├── tts.json
            ├── tts_meta.json
            ├── mix.json
            ├── render.json
            ├── subs.vi.srt
            ├── editor.json
            ├── mixed.wav
            └── tts/                # WAV từng câu và dub_track.wav
~~~

Settings và model cache nằm riêng với job data; xem [OPERATIONS.md](OPERATIONS.md) để biết path theo nền tảng.

## 6. Job state và recovery

~~~mermaid
stateDiagram-v2
    [*] --> idle
    idle --> running: Người dùng bắt đầu
    running --> review: Tới review stop
    review --> running: Continue
    running --> paused: Pause giữa stage
    paused --> running: Continue
    running --> cancelled: Cancel giữa stage
    cancelled --> running: Continue / Retry
    running --> failed: Stage hoặc lưu dữ liệu lỗi
    failed --> running: Retry / Continue
    running --> done: Tất cả stage thành công
    done --> [*]
~~~

Job có thể giữ state RUNNING khi app dừng bất thường; History hiển thị là gián đoạn. Recovery kiểm tra project, metadata, checkpoint và artifact, rồi tính stage sớm nhất cần chạy lại. Source identity khác yêu cầu xác nhận restart từ fetch. Discovery không chạy model/provider và không thay đổi source/output media; checkpoint hoặc metadata hỏng có thể được quarantine thành .corrupt để giữ bằng chứng.

## 7. Invariants và giới hạn

1. Một Orchestrator sở hữu một Job; BatchQueueWindow chạy nhiều Job tuần tự.
2. Startup không tự resume; chỉ đọc manifest để hiện thông báo queue còn dở.
3. Continue, rebuild, refresh URL và skip đều cần hành động tường minh.
4. Review intent chỉ được xóa khi Continue; Back/close lưu edit nhưng chưa duyệt.
5. Không publish output lên file đã tồn tại; MP4/SRT sidecar dùng chung basename.
6. Pause/cancel có hiệu lực giữa stage, không giết lời gọi model/network đang chạy.
7. Sửa subtitle text/timing, thêm hoặc xóa câu trong editor không tổng hợp lại hay retime TTS; dub track vẫn giữ audio và timing đã tạo.
8. VietDub STT gửi WAV tới service localhost do user khởi chạy; service không được bundle cùng app.
