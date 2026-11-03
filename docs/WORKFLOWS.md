# Luồng VietDub

Tài liệu này mô tả hành vi hiện có trong UI và core. Thành phần, data contract và module boundary nằm trong [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Xử lý một video

~~~mermaid
flowchart TD
    Start[Chọn tệp hoặc URL] --> Probe[Đọc metadata và rãnh âm thanh]
    Probe --> Config[Chọn track, output, giọng và review]
    Config --> Create[Tạo Job, lưu project và job record]
    Create --> Fetch[Fetch]
    Fetch --> Extract[Extract WAV]
    Extract --> ASR[Nhận transcript và speaker]
    ASR --> R1{Review transcript bật?}
    R1 -->|Có| SourceReview[Sửa text, speaker, gender, audience]
    R1 -->|Không| Gender[Ước tính gender]
    SourceReview --> Gender
    Gender --> Analyze[LLM phân tích quan hệ]
    Analyze --> Translate[Dịch zh sang vi]
    Translate --> R2{Review bản dịch bật?}
    R2 -->|Có| TranslationReview[Sửa nội dung và metadata]
    R2 -->|Không| TTS[Edge-TTS]
    TranslationReview --> TTS
    TTS --> Fit[Khớp thời lượng thoại]
    Fit --> Mix[Trộn audio]
    Mix --> Render[Render MP4 và subtitle]
    Render --> Finish[Preview hoặc mở editor]
~~~

Chế độ qua đêm tắt hai review stop để job không chờ người dùng. Job mới chỉ chạy sau khi app lưu Project và job record ban đầu.

## 2. Review và tiếp tục

~~~mermaid
sequenceDiagram
    participant Core as Orchestrator
    participant Store as Job/checkpoint store
    participant UI as Review UI
    participant User as Người dùng

    Core->>Store: Ghi review intent trước ASR hoặc translate
    Core->>Store: Lưu stage checkpoint và lifecycle
    Core-->>UI: Trả quyền điều khiển cho UI
    UI->>User: Hiển thị bảng transcript hoặc bản dịch
    User->>UI: Sửa và chọn Continue, Back hoặc đóng
    UI->>Store: Lưu edit; giữ pending review nếu chưa Continue
    User->>UI: Continue
    UI->>Store: Xác thực checkpoint, xóa pending intent
    UI->>Core: Chạy tiếp tại gender hoặc TTS
~~~

Back/close lưu thay đổi nhưng không đồng nghĩa đã duyệt. Nếu lưu thất bại, review window giữ nội dung để người dùng thử lại. Sau khi duyệt ASR, gender estimator vẫn chạy cho speaker chưa gắn nhãn và giữ lựa chọn male/female nhập tay.

## 3. Hàng đợi tuần tự

~~~mermaid
flowchart TD
    Main[Main window] --> Add[Thêm tệp local]
    Add --> Manifest[Lưu active_queue.json]
    Manifest --> Start[Người dùng bấm bắt đầu hoặc tiếp tục]
    Start --> Current[Đọc active entry]
    Current --> MakeJob[Tạo hoặc nạp đúng một Job]
    MakeJob --> Run[Chạy một Orchestrator]
    Run -->|DONE| MarkDone[Lưu entry done]
    Run -->|REVIEW / PAUSED / FAILED / CANCELLED| Block[Giữ entry active và chờ user]
    MarkDone --> More{Còn item?}
    More -->|Có| Next[Chuyển entry kế tiếp]
    More -->|Không| Clear[Xóa manifest đã hoàn tất]
    Block --> Action{Continue, Retry hoặc Skip}
    Action -->|Continue / Retry| Start
    Action -->|Skip| MarkSkip[Lưu skipped]
    MarkSkip --> More
~~~

Queue giữ thứ tự và active entry trong manifest. Item lỗi, đang review hoặc pause không tự nhường lượt cho item tiếp theo. Người dùng xác nhận continue/retry hoặc skip.

## 4. Startup và job history

~~~mermaid
sequenceDiagram
    participant App as MainWindow
    participant Queue as QueueStore
    participant History as JobHistoryDialog
    participant Recovery as JobRecovery
    participant User as Người dùng
    participant Core as Orchestrator

    App->>Queue: Đọc manifest queue khi mở app
    Queue-->>App: Hiện thông báo nếu còn queue
    Note over App: Không scan history, tải model hay gọi provider
    User->>History: Mở Lịch sử
    History->>Recovery: Lazy inspect job, project, checkpoint và source
    Recovery-->>History: Status, resume point, rebuild scope, blocked reason
    User->>History: Chọn mở review, tiếp tục, retry hoặc xem output/log
    History->>User: Yêu cầu xác nhận rebuild/refresh nếu source đổi
    User->>Core: Xác nhận tiếp tục
    Core->>Recovery: Kiểm tra job trước khi chạy
    Core-->>User: Chạy từ stage hợp lệ sớm nhất
~~~

Nếu app đóng khi record còn RUNNING, History hiển thị job gián đoạn. Resume kiểm tra source và artifact; URL đã tải được dùng lại nếu identity còn đúng. Source thay đổi cần xác nhận restart từ fetch.

## 5. State của job và queue

~~~mermaid
stateDiagram-v2
    [*] --> idle
    idle --> running
    running --> review
    review --> running
    running --> paused
    paused --> running
    running --> failed
    failed --> running
    running --> cancelled
    cancelled --> running
    running --> done
    done --> [*]
~~~

Job status được lưu riêng với queue state. Queue entry chỉ có queued, done hoặc skipped; review, paused, failed, cancelled và interrupted vẫn là việc chưa giải quyết. Queue không đánh dấu done trước khi job record lưu trạng thái hoàn tất.

## 6. Editor và xuất bản

~~~mermaid
sequenceDiagram
    participant Finish as FinishWindow
    participant Editor as VideoEditorWindow
    participant Draft as stages/editor.json
    participant Media as media.editor
    participant FFmpeg as FFmpeg
    participant Output as MP4/SRT

    Finish->>Editor: Mở editor
    Editor->>Draft: Nạp bản nháp nếu có
    Editor->>Editor: Preview video/dub và seek timeline
    Editor->>Draft: Debounce-save trim, subtitle và logo
    User->>Editor: Bấm Xuất video
    Editor->>Editor: So sánh subtitle với bản dùng để tạo TTS
    alt Text, thời gian hoặc số câu đã thay đổi
        Editor->>User: Cảnh báo và hỏi xác nhận subtitle-only
        alt Xác nhận
            User->>Editor: Đồng ý giữ audio hiện tại
            Editor->>Media: Gửi trim, segments, logo và subtitle mode
        else Hủy
            User->>Editor: Hủy xuất
            Editor-->>User: Giữ editor, không xuất
        end
    else Không thay đổi subtitle
        Editor->>Media: Gửi trim, segments, logo và subtitle mode
    end
    Media->>FFmpeg: Cắt media, overlay logo, burn subtitle nếu chọn
    FFmpeg-->>Media: Temporary MP4/SRT
    Media->>Output: Publish không ghi đè
    Output-->>Editor: Trả đường dẫn xuất thực tế
~~~

Editor cho phép cắt video, sửa subtitle text/timing, thêm/xóa câu, đóng logo và chọn burn-in/SRT. Nếu subtitle khác nội dung, thời gian hoặc số câu đã dùng để tạo TTS, editor hiển thị cảnh báo và yêu cầu xác nhận xuất theo chế độ subtitle-only. Audio lồng tiếng tiếp tục dùng track đã tạo trước đó.

## 7. Hành vi khi lỗi

- Stage lỗi: job thành FAILED và lưu stage cần tiếp tục cùng last_error; History/queue có thể Retry hoặc Continue.
- Checkpoint sai cấu trúc hoặc artifact thiếu/rỗng: stage không được dùng lại; các stage phụ thuộc phía sau được dựng lại.
- Metadata job/queue lỗi schema: giữ file bằng chứng .corrupt và báo trạng thái qua UI.
- URL source thay đổi: không dùng lại âm thầm download cũ; user xác nhận restart và tải lại.
- Export lỗi: file tạm không được lưu thành checkpoint hoàn tất; output đã có không bị thay thế.
- Lỗi dịch: provider tiếp theo được thử; nếu hết LLM provider, Google Translate miễn phí là fallback cuối và chất lượng đại từ có thể giảm.
