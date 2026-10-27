> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# VietDub Functional Upgrade Roadmap

**Ngày lập:** 2026-10-26
**Trạng thái hiện hành:** Phase 1–3 đã được triển khai; Phase 4–5 còn mở.
**Nguồn trạng thái runtime:** [Kiến trúc hiện hành](../../ARCHITECTURE.md), [luồng](../../WORKFLOWS.md).

Đây là roadmap theo giai đoạn. Nội dung “findings” bên dưới ghi nhận vấn đề tại thời điểm scan 2026-10-26; không dùng phần đó làm mô tả hành vi hiện tại.

## Phạm vi

Roadmap bao phủ desktop workflow, pipeline chín bước, job/checkpoint persistence, ASR/translation providers, Edge-TTS, media render/editor và overnight workflow.

## Trạng thái theo phase

| Phase | Mục tiêu | Trạng thái |
|---|---|---|
| 1. Data integrity | Guard transcript merge theo speaker/audience/gender; giữ edit khi merge/save lỗi | Đã triển khai và merge |
| 2. Batch queue | Queue video local tuần tự, status theo item, cô lập từng job | Đã triển khai; queue được persist |
| 3. Job history/recovery | Lưu queue/job lifecycle, inspect checkpoint/source, resume/rebuild tường minh | Đã triển khai và merge |
| 4. Đồng bộ subtitle/audio | Tạo lại speech đã sửa hoặc cho phép chọn rõ subtitle-only | Chưa triển khai |
| 5. Release evidence | Ma trận smoke cho model first-use, audio, Edge-TTS, render, recovery và Windows package | Chưa hoàn tất |

## Giới hạn còn mở

### Phase 4 — Đồng bộ subtitle và audio

Editor hiện cho sửa text/time subtitle, thêm/xóa câu, trim video và đóng logo. Sửa chữ không tạo lại audio TTS tương ứng. Hướng triển khai còn cần quyết định: re-synthesize các câu thay đổi, hoặc đánh dấu subtitle-only và hiển thị rõ lời đọc còn cũ.

### Phase 5 — Release evidence

Cần một báo cáo có thể lặp lại cho video đa dạng, model tải lần đầu, Edge-TTS, render, job recovery và Windows package. Không được suy ra kết quả live service/media từ compile hoặc static review.

## Các quyết định đã giữ

- Orchestrator xử lý một Job; batch scheduling nằm ở UI và chạy tuần tự.
- Không bỏ qua review tự động trừ khi user bật overnight mode.
- Không tự ghi đè file output hoặc xóa job/artifact.
- Khôi phục queue/job cần lựa chọn rõ ràng sau khi app mở lại.
- Phân biệt kiểm tra code với xử lý model, provider và media thật.

## Giới hạn của scan ban đầu

Scan ngày 2026-10-26 là source/documentation review. Nó không chứng minh model download, LLM provider, Edge-TTS, media render hoặc Windows packaging đã chạy thành công.
