# VietDub — Tổng quan kiến trúc

**Trạng thái:** implementation hiện hành
**Rà soát tài liệu:** 2026-10-27

VietDub là ứng dụng desktop PySide6 để lồng tiếng Việt cho video tiếng Trung. Mỗi video có một Job riêng; Orchestrator chỉ chạy một Job. Batch queue quản lý nhiều Job ở UI và chạy lần lượt để dữ liệu, checkpoint và log không trộn giữa các video.

~~~mermaid
flowchart LR
    User[Người dùng] --> UI[PySide6 UI]
    UI --> Worker[Worker thread]
    Worker --> Core[Orchestrator<br/>một Job]
    Core --> ASR[ASR và diarization]
    Core --> LLM[Phân tích và dịch]
    Core --> TTS[Edge-TTS]
    Core --> Media[FFmpeg media pipeline]
    Core --> Store[Project, checkpoints,<br/>job history]
    Queue[Persistent batch queue] --> UI
    History[History và recovery] --> UI
    ASR --> Models[Local model cache]
    LLM --> Providers[OpenAI / 9Router / Ollama<br/>Google Translate fallback]
    TTS --> Edge[Microsoft Edge-TTS]
    Media --> Output[MP4 và SRT]
~~~

Pipeline gồm chín stage: fetch, extract, ASR, gender, analyze, translate, TTS, mix và render. Người dùng có thể duyệt transcript sau ASR và duyệt bản dịch trước TTS. Chế độ qua đêm tắt các điểm dừng review. Pause/cancel có hiệu lực sau khi stage hiện tại hoàn tất.

## Nguyên tắc hiện hành

- UI sở hữu input, confirmation, review, history và queue; tác vụ dài chạy ngoài Qt main thread.
- Core sở hữu Project, Job, orchestration, checkpoint và quyết định recovery; core không mở dialog.
- Một queue entry chạy trọn một Job trước khi entry kế tiếp bắt đầu.
- Model ASR được tải lần đầu khi bắt đầu stage ASR, không tải khi mở app.
- Recovery kiểm tra source, metadata, checkpoint và artifact trước khi đề nghị continue/rebuild; app không tự chạy job khi khởi động.
- Output được publish vào tên chưa tồn tại; file người dùng đã có không bị ghi đè.
- Subtitle text trong editor độc lập với audio TTS đã tạo: sửa chữ không tổng hợp lại giọng.
- VietDub STT là adapter tùy chọn tới service riêng trên localhost, không được bundle cùng app.

Sơ đồ module, pipeline, lifecycle và data layout đầy đủ nằm trong [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Luồng end-to-end nằm trong [docs/WORKFLOWS.md](docs/WORKFLOWS.md). Mục lục tài liệu hiện hành và lịch sử nằm trong [docs/README.md](docs/README.md).

VietDub phát hành theo GPL-3.0. Các module adapt từ pyVideoTrans giữ credit trong header file nguồn.
