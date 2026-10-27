# Tài liệu VietDub

Tài liệu chia thành hướng dẫn dùng app, mô tả implementation hiện tại và hồ sơ lịch sử. Khi nội dung cũ khác mã nguồn, dùng code cùng các tài liệu kiến trúc hiện hành làm chuẩn.

## Tài liệu hiện hành

| Tài liệu | Dành cho | Nội dung |
|---|---|---|
| [README](../README.md) | Người dùng | Tính năng và bắt đầu nhanh |
| [DESIGN](../DESIGN.md) | Tổng quan | Sơ đồ kiến trúc rút gọn |
| [Kiến trúc](ARCHITECTURE.md) | Kỹ sư/SA | Module, pipeline, dữ liệu, state và ranh giới dịch vụ |
| [Luồng](WORKFLOWS.md) | Người dùng và kỹ sư | Xử lý video, review, queue, recovery và editor |
| [Vận hành](OPERATIONS.md) | Người cài đặt | Phụ thuộc, model, dữ liệu và troubleshooting |
| [Phát triển](DEVELOPMENT.md) | Nhà phát triển | Cấu trúc repo, ranh giới code, kiểm tra và build |
| [Benchmark ASR](ASR_BENCHMARK_2026-10-25.md) | Người chọn backend | Kết quả trên một video; không phải chứng nhận tổng quát |

## Hồ sơ thiết kế và triển khai

Thư mục superpowers/specs và superpowers/plans lưu bối cảnh, quyết định và handoff của các đợt phát triển. Đây là hồ sơ lịch sử, không phải hướng dẫn chạy app hay checklist release hiện hành.

- [Functional roadmap — trạng thái triển khai](superpowers/specs/2026-10-26-vietdub-functional-roadmap.md)
- [Kế hoạch functional upgrade](superpowers/plans/2026-10-26-vietdub-functional-roadmap.md)
- [Design job history và recovery](superpowers/specs/2026-10-26-job-history-recovery-design.md)
- [Design batch queue](superpowers/specs/2026-10-26-batch-queue-design.md)
- [Design safe transcript merge](superpowers/specs/2026-10-26-safe-transcript-merge-design.md)
- [Design reliability hardening](superpowers/specs/2026-10-25-reliability-hardening-design.md)
- [Design production UI](superpowers/specs/2026-10-26-vietdub-production-ui-design.md)

Các spec/plan lịch sử được giữ để bảo toàn quyết định và acceptance criteria. Header mỗi file trỏ về tài liệu runtime hiện hành.
