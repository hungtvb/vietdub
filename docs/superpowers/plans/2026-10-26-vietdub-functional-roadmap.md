> **Hồ sơ lịch sử:** nội dung này ghi nhận bối cảnh, quyết định và kế hoạch tại thời điểm tạo; không phải hướng dẫn runtime hoặc trạng thái release hiện tại. Dùng [ARCHITECTURE.md](../../ARCHITECTURE.md), [WORKFLOWS.md](../../WORKFLOWS.md) và [mục lục tài liệu](../../README.md) để tra cứu trạng thái hiện hành.

# VietDub Functional Upgrade Plan — Execution Record

**Trạng thái:** Phase 1–4 đã triển khai; Phase 5 chưa hoàn tất.
**Roadmap gốc:** [Functional upgrade roadmap](../specs/2026-10-26-vietdub-functional-roadmap.md).
**Tài liệu runtime hiện hành:** [Kiến trúc](../../ARCHITECTURE.md), [luồng](../../WORKFLOWS.md).

Đây là handoff theo giai đoạn, không còn active worktree plan.

## Phase 1 — Existing-feature integrity: hoàn tất

- Guard source transcript merge để không gộp khác speaker, audience hoặc gender theo cách làm mất metadata.
- Giữ edit khi merge bị từ chối hoặc persistence lỗi.
- Review source/translation save và navigation paths.
- Code được triển khai trong nhánh existing-feature.

## Phase 2 — Sequential batch queue: hoàn tất

- Cho thêm nhiều video local, hiển thị queue item status/progress.
- Mỗi lúc chỉ chạy một Orchestrator và tách checkpoint/output theo job.
- Giữ queue tại review, pause, cancel hoặc failure; không tự nhảy item.
- Bổ sung manifest bền vững và restore flow ở Phase 3.

## Phase 3 — Job history và restart recovery: hoàn tất

- Lưu job lifecycle, source identity và active queue manifest.
- Tìm stage hợp lệ sớm nhất và xác nhận rebuild khi source/artifact thay đổi.
- Giữ pending review sau Back/close/crash; Continue là thao tác duyệt rõ ràng.
- Thêm history actions và startup queue notice; startup không tự chạy model/provider.

## Phase 4 — Subtitle/audio editing consistency: đã triển khai

- So sánh subtitle trong editor với transcript/TTS ban đầu.
- Báo rõ subtitle-only và yêu cầu xác nhận khi text, timing hoặc số câu thay đổi.
- Giữ nguyên audio đã tạo; tái tạo TTS cho câu sửa tiếp tục là giới hạn đã biết.

## Phase 5 — Release readiness và real-media evidence: chưa hoàn tất

- Xây dựng ma trận video đa dạng, first-use model download, provider/TTS, render, restart recovery và Windows packaged startup.
- Ghi riêng các dịch vụ không thể gọi và giới hạn nền tảng.
- Không diễn giải compile/static review thành bằng chứng inference hoặc render thật.

## Quy tắc handoff

Tài liệu này ghi nhận trạng thái của roadmap; dùng [docs/README.md](../../README.md) để tìm hướng dẫn hiện hành. Không dùng checkbox/phase đã qua làm checklist release.
