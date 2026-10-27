# Phát triển VietDub

## 1. Môi trường

Cài virtualenv và dependencies theo [OPERATIONS.md](OPERATIONS.md#2-cài-từ-mã-nguồn). Entry point là main.py: tạo QApplication, nạp Settings, áp dụng theme và mở MainWindow.

Các lệnh kiểm tra dự án:

~~~bash
python -m pytest tests/ -v
python -m py_compile main.py core/*.py project/*.py media/*.py asr/*.py translation/*.py tts/*.py speaker/*.py ui/*.py
git diff --check
~~~

Mở app và chạy kiểm tra cấu trúc không cần tải model. Model/service smoke test và media end-to-end cần được báo riêng với kiểm tra code; xem [hướng dẫn vận hành](OPERATIONS.md).

## 2. Bản đồ repository

| Đường dẫn | Trách nhiệm |
|---|---|
| main.py | Entry point desktop |
| core/job.py | Job đơn cho một video |
| core/orchestrator.py | Pipeline tuần tự chín stage cho một Job |
| core/checkpoint.py | Stage order, checkpoint validation/invalidation |
| core/job_store.py | Versioned lifecycle metadata và source identity |
| core/queue_store.py | Manifest cho active batch queue |
| core/job_recovery.py | Discovery, checkpoint/source inspection và resume decision |
| project/schema.py | Project, Segment, Speaker |
| project/io.py | Serialize Project và stage data |
| asr/ | Whisper, FunASR/CAM++, Qwen/ForcedAligner, VietDub STT adapter |
| speaker/gender.py | Pitch-based gender estimation |
| translation/ | Provider API, relation analysis, prompts, validation, fallback |
| tts/ | Edge-TTS, duration fit và audio track assembly |
| media/ | Fetch, FFmpeg, extraction, mix, render, subtitle, editor export |
| ui/main_window.py | Chọn nguồn, cấu hình nhanh, khởi chạy và recovery notice |
| ui/progress.py | Worker UI, tiến độ/log/control và review handoff |
| ui/review_source.py, ui/review_vi.py | Review source và bản dịch |
| ui/batch_queue.py, ui/job_history.py | Queue và history surface |
| ui/finish.py, ui/editor.py | Preview và editor |
| docs/ | Hướng dẫn hiện hành, benchmark, lịch sử spec/plan |
| packaging/vietdub.spec | PyInstaller onedir packaging |

## 3. Ranh giới module

- UI sở hữu input, confirmation, review và hiển thị trạng thái. Không chạy network, FFmpeg hoặc model inference trên Qt main thread.
- Core không import Qt và không mở dialog. Worker nhận một Job, chạy Orchestrator rồi trả status/error qua callback/signal.
- Orchestrator chỉ chạy một Job. Queue không thêm concurrency; mỗi entry khởi chạy một runner rồi chờ trạng thái cuối.
- Mỗi stage phải xác định checkpoint/data contract, artifact bắt buộc và invalidation boundary.
- Discovery khi app mở không được chạy model/provider hoặc sửa source/output media. Resume/rebuild cần user action tường minh.
- Render/editor export phải ghi tệp tạm cùng filesystem và publish no-replace. Chỉ lưu đường dẫn thực sau khi publish thành công.
- Network/model client được tạo lazy ở bước sử dụng, không lúc import app.

## 4. Thêm backend ASR

1. Thêm adapter dưới asr/; không tải model ở module import.
2. Giữ interface transcribe(audio_path) → list[Segment].
3. Validate timestamp hữu hạn, start ≥ 0, end > start, text không rỗng và speaker ID hợp lệ.
4. Gắn confidence/needs_review nếu model không chắc chắn.
5. Đăng ký backend trong asr/factory.py và SettingsDialog.
6. Dùng CAM++ riêng nếu diarization của model chưa được kiểm chứng.
7. Cập nhật dependency, first-use download, cache, data boundary và giới hạn chất lượng trong tài liệu.

## 5. Thêm translation provider

Provider triển khai BaseTranslator._chat(system, user); orchestration gọi analyze() và translate(). Giữ số lượng và ID segment ổn định. Parse/validate model output trước khi lưu. Prompt nhận speaker relations, audience, proper nouns và video metadata. Không xóa needs_review khi dùng fallback chất lượng thấp.

## 6. Thay đổi pipeline, recovery hoặc queue

Trước khi thêm stage, cập nhật stage list trong core/checkpoint.py và core/orchestrator.py. Xác định output artifact, checkpoint validity, invalidation boundary, resume behavior và review boundary. Job state khác queue state; queue không đánh dấu done trước khi job record lưu DONE.

Metadata JSON cần schema version, atomic write và quarantine không ghi đè file bằng chứng cũ. Thay schema phải giữ tương thích hoặc mô tả migration. Không tự di chuyển job cũ hoặc xóa output.

## 7. UI worker và lifecycle

Dùng QThread/worker cho model, network, metadata probing và FFmpeg. Giữ reference tới worker/thread tới khi finished signal được xử lý. Pause/cancel hiện có hiệu lực giữa stage; không dùng terminate() để giết model/network operation.

Back/close của review phải lưu edit trước. Chỉ Continue xóa review intent. Nếu save lỗi, giữ nội dung trên màn hình và cho phép thử lại.

## 8. Đóng gói

Build đích Windows 11:

~~~powershell
pip install pyinstaller
pyinstaller packaging/vietdub.spec
~~~

Model không nằm trong bundle. Nếu cần backend Qwen, cài requirements-qwen.txt trước khi build. FFmpeg binaries chỉ được bundle nếu có trong packaging/bin. Xem packaging/bin/README.txt và [OPERATIONS.md](OPERATIONS.md).

## 9. Nguồn tài liệu

Kiến trúc đang chạy nằm trong [ARCHITECTURE.md](ARCHITECTURE.md); diagram hành vi nằm trong [WORKFLOWS.md](WORKFLOWS.md). Superpowers spec/plan được lưu để bảo toàn quyết định và handoff, không phải checklist release hiện hành.
