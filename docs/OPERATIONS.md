# Cài đặt và vận hành

## 1. Yêu cầu

- Python 3.10 trở lên khi chạy từ mã nguồn.
- FFmpeg và FFprobe trong PATH, hoặc khai báo đường dẫn FFmpeg trong Cài đặt.
- Windows 11 là đích đóng gói chính. Code có path theo Linux/macOS nhưng đây không phải chứng nhận cho build/release các nền tảng đó.
- CPU chạy được Whisper/FunASR; Qwen trên CPU có thể chậm và dùng nhiều RAM. GPU không bắt buộc.
- Internet cho lần tải model đầu tiên và cho dịch vụ bên ngoài.

## 2. Cài từ mã nguồn

Windows PowerShell:

~~~powershell
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
python main.py
~~~

Linux/macOS:

~~~bash
python -m venv .venv
source .venv/bin/activate
pip install torch
pip install -r requirements.txt
python main.py
~~~

Cài thêm Qwen3-ASR và ForcedAligner nếu chọn backend Qwen:

~~~bash
pip install -r requirements-qwen.txt
~~~

Kiểm tra FFmpeg:

~~~bash
ffmpeg -version
ffprobe -version
~~~

## 3. Build ứng dụng Windows

1. Cài Python 3.10+, FFmpeg và PyInstaller.
2. Cài dependencies như phần trên.
3. Đặt ffmpeg.exe và ffprobe.exe vào packaging/bin.
4. Chạy:

~~~powershell
pyinstaller packaging/vietdub.spec
~~~

Kết quả là thư mục onedir dist/VietDub với VietDub.exe bên trong. Model weights không được bundle. Build có console để debug bằng cách đặt VIETDUB_CONSOLE=1 trước lệnh build.

## 4. Model và mạng

Mở app không tải model. Model chỉ được nạp khi bắt đầu stage ASR:

| Backend | Model/cache |
|---|---|
| Whisper large-v3-turbo | Hugging Face cache |
| FunASR ASR, VAD, punctuation, CAM++ | ModelScope cache |
| Qwen3-ASR và ForcedAligner | Hugging Face cache; cần requirements-qwen.txt |
| VietDub STT | Service riêng tải và quản lý model; app gửi audio qua loopback |

Cache mặc định ở thư mục models cạnh settings. Adapter tôn trọng HF_HOME hoặc MODELSCOPE_CACHE nếu user đã thiết lập. Lần tải đầu cần mạng và dung lượng trống; Whisper/FunASR/Qwen có thể dùng local sau khi model đã tải.

Các ranh giới mạng:

- URL video được yt-dlp tải về nếu user chọn nguồn link.
- Model weights được lấy từ kho tương ứng khi cần.
- Transcript và nội dung liên quan được gửi tới dịch vụ LLM đã chọn để phân tích/dịch.
- Edge-TTS gửi nội dung câu tới dịch vụ Microsoft để tạo tiếng nói.
- Backend VietDub STT stream file WAV tới server do user chạy trên 127.0.0.1:8768; adapter từ chối URL server khác localhost.

## 5. Cấu hình dịch vụ

Mở **Cài đặt**:

| Nhóm | Cấu hình |
|---|---|
| Dịch thuật | OpenAI API key, URL/model; 9Router key/URL/model; Ollama URL/model |
| ASR | Whisper, FunASR, Qwen hoặc VietDub STT; lựa chọn backend và quality cho service |
| Giọng đọc | Giọng nam/nữ, tốc độ, cao độ và số request đồng thời |
| Video | FFmpeg, volume dub/tiếng gốc, burn/SRT, font, cỡ/màu phụ đề, CRF |
| Tên riêng | Từ điển proper nouns dùng làm ngữ cảnh ASR và dịch |

Settings lưu thành JSON trong hồ sơ user. API key được lưu trong settings JSON local; bảo vệ quyền truy cập profile và không đưa file này vào git, screenshot hoặc bug report.

Dịch vụ dịch và Edge-TTS cần mạng. Ollama cần server local đang chạy và model đã được tải về riêng.

## 6. Tích hợp VietDub STT local

VietDub STT không nằm trong repository desktop. Cài package service riêng rồi chạy:

~~~bash
python -m vietdub_stt.api
~~~

Mặc định service lắng nghe trên 127.0.0.1:8768. Trong Cài đặt → ASR, chọn VietDub STT, chọn Fast (Qwen 0.6B) hoặc Quality (Qwen 1.7B), rồi chạy job. App gọi /v1/transcribe, stream WAV, giới hạn input 512 MiB và xác thực response schema. Nếu server chưa chạy hoặc response sai, job báo lỗi; không tự tạo transcript thay thế. CAM++ diarization vẫn chạy trong app.

## 7. Vị trí dữ liệu

| Dữ liệu | Windows | macOS | Linux |
|---|---|---|---|
| Settings | %APPDATA%/VietDub/settings.json | ~/.config/VietDub/settings.json | ~/.config/VietDub/settings.json |
| Jobs, queue, run log | %LOCALAPPDATA%/VietDub (fallback %APPDATA%) | ~/Library/Application Support/VietDub | $XDG_DATA_HOME/VietDub hoặc ~/.local/share/VietDub |
| Model cache mặc định | %APPDATA%/VietDub/models | ~/.config/VietDub/models | ~/.config/VietDub/models |

Trên Windows, settings/model cache dùng %APPDATA%, còn job data ưu tiên %LOCALAPPDATA%. Trên macOS/Linux, XDG_DATA_HOME chỉ điều chỉnh data directory, không đổi settings path.

Mỗi job có project.json, job.json, run.log, stage JSON và artifact trung gian riêng. URL source được tải vào thư mục job. Output video lưu ở vị trí đã chọn và dùng tên mới nếu target tồn tại. VietDub không tự dọn lịch sử job hoặc model cache.

Job cũ được tạo cạnh source code không tự di chuyển sang data directory mới; app không xóa thư mục cũ.

## 8. Khắc phục sự cố

| Tình trạng | Nguyên nhân thường gặp | Hành động |
|---|---|---|
| Không đọc được video | Thiếu FFmpeg/FFprobe hoặc codec lỗi | Kiểm tra hai lệnh version; thử file khác hoặc đặt ffmpeg_path |
| ASR tải lâu ở lần đầu | Model chưa có trong cache | Giữ mạng và chờ stage ASR; lần sau adapter dùng cache |
| Không chọn được Qwen | Chưa cài package tùy chọn | Cài requirements-qwen.txt rồi mở lại app |
| Ollama offline | Server/model chưa chạy | Chạy ollama serve, ollama pull <model>, kiểm tra URL |
| Dịch thất bại | API key, URL, quota hoặc mạng | Kiểm tra settings; provider kế tiếp có thể được thử; xem run.log |
| Edge-TTS thất bại | Mạng hoặc voice service | Kiểm tra mạng/voice và Retry job từ stage TTS |
| Job dừng ở review | Có review intent chưa được Continue | Mở Lịch sử hoặc queue, mở review rồi chọn Continue |
| Source thay đổi | Path, size, mtime hoặc URL khác | Xác nhận rebuild từ fetch; URL sẽ được tải lại |
| Output có hậu tố _2 | Tên MP4 hoặc SRT đã tồn tại | Đây là bảo vệ file cũ; kiểm tra đường dẫn export thực tế |
| Job cũ không hiện | Job nằm ở thư mục source-adjacent cũ | Thư mục cũ không tự migration; giữ nguyên và phục hồi thủ công nếu cần |
