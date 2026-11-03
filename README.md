# VietDub

Desktop app lồng tiếng **video đa ngôn ngữ sang tiếng Việt** (PySide6).
Pipeline 9 bước: video → tách audio → nhận diện ngôn ngữ nguồn và chọn ASR
→ phân biệt người nói → phân tích nhân vật → dịch có ngữ cảnh → tổng hợp giọng
→ trộn audio → ghép MP4. Tính năng có kiểm tra thủ công và checkpoint.

### ASR thông minh, dùng chung cho nhiều video

Bắt đầu một video mới → chọn **Ngôn ngữ video = Tự động nhận diện**.
VietDub nghe tối đa 3 đoạn âm thanh phân bố từ đầu đến cuối video
(tránh nhận nhầm theo chữ trên màn hình hoặc nhạc mở đầu):

| Ngôn ngữ | ASR mặc định | Xử lý người nói |
|---|---|---|
| Quan thoại Trung Quốc (zh, đủ chắc chắn) | FunASR / Paraformer | CAM++ + pyannote toàn video khi có token |
| Anh, Nhật, Hàn, Pháp, Tây Ban Nha... | Whisper multilingual | pyannote Community-1 |
| Xen ngôn ngữ, không đủ chắc chắn | Whisper multilingual + cảnh báo QA | pyannote + duyệt thủ công |

Đây là quy tắc chọn *mô hình khởi đầu*, không đảm bảo FunASR thắng Whisper
trên tất cả nguồn tiếng Trung (tiếng địa phương, lồng nhạc, tiếng ồn).
Có thể **chọn tiếng Trung và ép Whisper** trong Cài đặt để so sánh.

Thành phần nâng cao yêu cầu `pip install -r requirements-asr-hybrid.txt`.
Hugging Face Community-1 cần đồng ý điều khoản model trước, sau đó đặt
`HF_TOKEN` trong biến môi trường (khuyên dùng) hoặc phần Cài đặt.
FunASR vẫn có thể nhận dạng lời tiếng Trung khi không có token, nhưng khi đó
việc nối ID speaker qua các chunk dài sẽ cần kiểm tra bổ sung.

**Không tự phê duyệt:** ASR chỉ sinh transcript và bằng chứng. Những dòng
thiếu confidence, chưa rõ speaker hoặc thiếu forced alignment luôn có cờ QA;
việc truy cập model thành công không tương đương nhân vật đã được xác minh.

### Video tiếng Trung dùng để kiểm thử

Workflow `.github/workflows/vietdub-chinese-regression.yml` tải clip
phỏng vấn bóng đá Quan thoại trên Wikimedia Commons (1 phút 32 giây),
do **中国新闻社** thực hiện, mô tả giấy phép **CC BY 3.0**
(trang nguồn còn ghi chú cần license review):

https://commons.wikimedia.org/wiki/File:〖两会30秒〗水庆霞：中国女足非世界顶级，但会不断追赶.webm

Lần chạy kiểm tra từ **audio thật**: ngôn ngữ, engine được chọn, timestamp,
phân đoạn FunASR và cờ QA. Chưa có transcript người nghe xác minh nên
**không công bố CER/WER giả**. Video nguồn không commit vào GitHub.

## Tính năng

- Nhận video từ tệp hoặc URL yt-dlp hỗ trợ; chọn rãnh âm thanh nếu video có nhiều track.
- ASR bằng Whisper large-v3-turbo, FunASR, Qwen3-ASR hoặc dịch vụ VietDub STT chạy riêng trên localhost.
- CAM++ gắn nhãn người nói; pitch ước tính giới tính. Người dùng có thể sửa transcript, người nói và giới tính.
- Phân tích quan hệ và dịch qua OpenAI-compatible API, 9Router hoặc Ollama; Google Translate miễn phí là fallback cuối.
- Edge-TTS tạo giọng tiếng Việt; co giãn hoặc tách câu dài để khớp thời lượng.
- Trộn dub với tiếng gốc giảm nhỏ; xuất phụ đề burn-in hoặc SRT rời.
- Lưu checkpoint từng bước, job history, hàng đợi video tuần tự và trạng thái review để tiếp tục sau khi đóng app.
- Editor cho phép cắt video, sửa nội dung/thời gian subtitle, thêm/xóa câu, đóng logo và xuất bản mới; nếu subtitle khác lời đọc đã tạo, app cảnh báo và yêu cầu xác nhận giữ nguyên audio lồng tiếng.

## Bắt đầu nhanh

VietDub nhắm tới Windows 11. Cần Python 3.10 trở lên khi chạy từ mã nguồn và FFmpeg/FFprobe trong PATH.

~~~powershell
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
# Bắt buộc cho chế độ ASR tự động/Whisper + pyannote:
pip install -r requirements-asr-hybrid.txt
```

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

1. Cài Python 3.10+ (python.org, tick "Add python.exe to PATH").
2. Tải ffmpeg bản `release essentials`
   ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/)), giải nén, thêm thư
   mục `bin` vào PATH (kiểm tra: mở cmd gõ `ffmpeg -version`).
3. Mở cmd trong thư mục VietDub:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   pip install -r requirements-asr-hybrid.txt
   python main.py
   ```

Model local được tải khi bắt đầu ASR lần đầu, không tải lúc mở app. Dịch qua OpenAI/9Router gửi transcript tới nhà cung cấp đã chọn; Edge-TTS cần mạng. Ollama dùng máy chủ/model local nếu đã cài sẵn.

1. Cài Python 3.10+ như cách A, rồi trong cmd tại thư mục VietDub:
   ```
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   pip install -r requirements-asr-hybrid.txt
   pip install pyinstaller
   ```
2. Tải ffmpeg bản Windows `release essentials`
   ([gyan.dev](https://www.gyan.dev/ffmpeg/builds/)), giải nén, chép
   **ffmpeg.exe** + **ffprobe.exe** vào thư mục `packaging\bin\`
   (xem `packaging\bin\README.txt`).
3. Build:
   ```
   pyinstaller packaging\vietdub.spec
   ```
   File chạy: `dist\VietDub\VietDub.exe` — chép cả thư mục `VietDub`
   đi đâu cũng chạy được, không cần cài Python.
   (Muốn hiện cửa sổ console để xem log khi debug:
   `set VIETDUB_CONSOLE=1` trước khi chạy pyinstaller.)

- Editor chưa tạo lại audio TTS cho subtitle được sửa. Khi có thay đổi nội dung, thời gian hoặc số câu, cần xác nhận chế độ subtitle-only; audio lồng tiếng giữ nguyên và có thể không khớp subtitle.
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
