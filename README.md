# VietDub

VietDub là ứng dụng desktop PySide6 tạo bản lồng tiếng Việt cho video tiếng Trung. App nhận transcript và timestamp, gắn người nói, phân tích quan hệ xưng hô, dịch, tạo giọng đọc, trộn âm thanh và xuất video cùng phụ đề.

## Tính năng

- Nhận video từ tệp hoặc URL yt-dlp hỗ trợ; chọn rãnh âm thanh nếu video có nhiều track.
- ASR bằng Whisper large-v3-turbo, FunASR, Qwen3-ASR hoặc dịch vụ VietDub STT chạy riêng trên localhost.
- CAM++ gắn nhãn người nói; pitch ước tính giới tính. Người dùng có thể sửa transcript, người nói và giới tính.
- Phân tích quan hệ và dịch qua OpenAI-compatible API, 9Router hoặc Ollama; Google Translate miễn phí là fallback cuối.
- Edge-TTS tạo giọng tiếng Việt; co giãn hoặc tách câu dài để khớp thời lượng.
- Trộn dub với tiếng gốc giảm nhỏ; xuất phụ đề burn-in hoặc SRT rời.
- Lưu checkpoint từng bước, job history, hàng đợi video tuần tự và trạng thái review để tiếp tục sau khi đóng app.
- Editor cho phép cắt video, sửa nội dung/thời gian subtitle, thêm/xóa câu, đóng logo và xuất bản mới.

## Bắt đầu nhanh

VietDub nhắm tới Windows 11. Cần Python 3.10 trở lên khi chạy từ mã nguồn và FFmpeg/FFprobe trong PATH.

~~~powershell
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python main.py
~~~

Linux/macOS: tạo virtualenv, cài PyTorch và requirements.txt tương tự, rồi chạy python main.py. Xem [hướng dẫn vận hành](docs/OPERATIONS.md) để cài FFmpeg, Qwen tùy chọn, VietDub STT hoặc build .exe.

## Luồng sử dụng

1. Chọn video hoặc dán URL, chờ đọc metadata, chọn rãnh âm thanh nếu cần.
2. Cấu hình dịch vụ trong Cài đặt.
3. Bấm **Bắt đầu lồng tiếng**. VietDub tạo job riêng và ghi checkpoint theo từng bước.
4. Duyệt transcript sau ASR và bản dịch trước TTS nếu bật review stop. Chế độ qua đêm bỏ qua hai điểm dừng.
5. Xem thành phẩm hoặc mở **Biên tập video**.

Thêm nhiều tệp local vào **Hàng đợi** để chạy lần lượt. Queue được lưu giữa các lần mở app. **Lịch sử** cho phép mở review đang chờ, tiếp tục job bị dừng/lỗi/gián đoạn hoặc xem output. App không tự chạy tiếp khi khởi động.

## ASR và dịch vụ ngoài

Backend mặc định là Whisper large-v3-turbo cho transcript/timestamp kết hợp CAM++ cho người nói. Có thể chọn FunASR, Qwen3-ASR-1.7B cùng ForcedAligner, hoặc VietDub STT local. Qwen cần cài thêm:

~~~bash
pip install -r requirements-qwen.txt
~~~

Model local được tải khi bắt đầu ASR lần đầu, không tải lúc mở app. Dịch qua OpenAI/9Router gửi transcript tới nhà cung cấp đã chọn; Edge-TTS cần mạng. Ollama dùng máy chủ/model local nếu đã cài sẵn.

## Giới hạn hiện tại

- Sửa hoặc thêm/xóa subtitle text/timing trong editor không tạo lại hay retime audio TTS; bản dub tiếp tục dùng audio đã tạo trước khi chỉnh subtitle.
- VietDub STT là tích hợp tùy chọn; chưa có đánh giá end-to-end trên model thật.
- Benchmark ASR hiện tại là đánh giá định tính trên một video, không có phụ đề chuẩn để tính CER/WER.
- Qwen 1.7B trên CPU có thể chậm và dùng nhiều RAM. Chất lượng/tốc độ phụ thuộc máy, model và video.
- Nếu Edge-TTS lỗi toàn bộ, job dừng ở trạng thái lỗi để người dùng chạy lại.

## Tài liệu

- [Mục lục tài liệu](docs/README.md)
- [Kiến trúc](docs/ARCHITECTURE.md)
- [Luồng xử lý và recovery](docs/WORKFLOWS.md)
- [Cài đặt và vận hành](docs/OPERATIONS.md)
- [Phát triển và đóng gói](docs/DEVELOPMENT.md)
- [Benchmark ASR 2026-10-25](docs/ASR_BENCHMARK_2026-10-25.md)

VietDub phát hành theo GPL-3.0. Module adapt từ pyVideoTrans giữ credit trong header file nguồn liên quan.
