# VietDub

Desktop app lồng tiếng video tiếng Trung sang tiếng Việt (PySide6).
Pipeline 9 bước: lấy video (file/link) → tách audio → nghe + tách loa
(Whisper large-v3-turbo + FunASR/CAM++; tùy chọn Qwen3-ASR + ForcedAligner + CAM++)
→ đoán giới tính bằng pitch → LLM phân tích quan hệ → dịch
(OpenAI GPT, 9Router hoặc Ollama) → lồng tiếng Edge-TTS
→ trộn audio → ghép video + phụ đề.

License: GPL-3.0 (xem `LICENSE`). Một số module adapt từ
[pyVideoTrans](https://github.com/jianchang512/pyvideotrans) (jianchang512,
GPL-3.0) — credit ghi trong header từng file.

## Cài đặt (developer)

```bash
cd vietdub
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Windows CPU: cài torch bản CPU trước
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
# Tùy chọn nếu muốn bật backend Qwen:
pip install -r requirements-qwen.txt
```

Cần thêm: **ffmpeg** có trong PATH
([tải tại gyan.dev](https://www.gyan.dev/ffmpeg/builds/) bản Windows,
giải nén rồi thêm `bin` vào PATH).

## Chạy test

```bash
pytest tests/ -v
```

## Hướng dẫn cho Tony (Windows 11)

Có 2 cách chạy — chọn 1:

### Cách A — chạy trực tiếp bằng Python (nhanh, dễ debug)

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
   # Tùy chọn để chọn backend Qwen trong Cài đặt -> ASR:
   pip install -r requirements-qwen.txt
   python main.py
   ```

### Cách B — build file .exe một lần, chạy mãi mãi (khuyên dùng)

1. Cài Python 3.10+ như cách A, rồi trong cmd tại thư mục VietDub:
   ```
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   # Tùy chọn nếu muốn đóng gói backend Qwen:
   pip install -r requirements-qwen.txt
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

### Lần chạy đầu tiên (cả 2 cách)

- Mở app không tải model. Trọng số chỉ được tải ở lần đầu chạy bước Nhận dạng
  (ASR), rồi lưu cache để các lần sau dùng lại. Whisper tải từ Hugging Face;
  FunASR, VAD, dấu câu và CAM++ tải từ ModelScope. Model Whisper lưu trong
  `%APPDATA%\VietDub\models\huggingface`, FunASR trong
  `%APPDATA%\VietDub\models`. Cần mạng ở lần tải đầu; ASR chạy offline sau đó.
- Muốn chọn backend Qwen, cài thêm `pip install -r requirements-qwen.txt`.
  Khi chạy ASR bằng Qwen, app mới tải model ASR 1.7B và ForcedAligner
  (khoảng 6 GB tổng), tuần tự với FunASR/CAM++ để giảm RAM; trên CPU chậm hơn
  Whisper nhiều.
- OpenAI/9Router chỉ gọi API ở bước phân tích/dịch; Edge-TTS kết nối dịch vụ
  Microsoft khi tổng hợp giọng. Nếu chọn Ollama, model phải được cài riêng bằng
  `ollama pull <tên-model>`; app chỉ kết nối tới model đó khi cần phân tích/dịch.
- **Edge-TTS cần mạng** mới lồng được tiếng (giọng Microsoft online).
  Nếu Edge-TTS lỗi toàn bộ, bước lồng tiếng báo lỗi để chạy lại; không tự
  đổi sang dịch vụ TTS khác.
- ASR mặc định dùng **Whisper large-v3-turbo** cho transcript và timestamps;
  **CAM++** gán nhãn loa từ lượt thoại FunASR. Có thể chọn FunASR trực tiếp ở
  **Cài đặt → ASR** nếu muốn ưu tiên tốc độ hoặc giảm bộ nhớ. Backend **Qwen
  1.7B + ForcedAligner + CAM++** bổ sung timestamp và nhãn loa cho Qwen.
- Dịch mặc định qua **OpenAI API** (`gpt-4.1`). Nhập OpenAI API key ở
  **Cài đặt → Dịch thuật**. API tính phí riêng, không dùng chung gói
  ChatGPT. Có thể chọn 9Router hoặc Ollama thay thế.

### Dùng app

1. Chọn video (tab File) hoặc dán link Douyin/TikTok/YouTube (tab Link),
   nhấn **Bắt đầu**. Bật **Chế độ qua đêm** nếu muốn máy tự chạy hết
   9 bước không dừng duyệt (sáng dậy có phim). Muốn xử lý nhiều video
   local lần lượt, bấm **Hàng đợi**; phase hiện tại dùng rãnh âm thanh đầu
   tiên và danh sách chỉ tồn tại trong phiên app đang mở.
2. Kết quả: `<tên video>_vidub.mp4` + file `.srt` trong thư mục đã chọn.
   Log từng job nằm trong thư mục dữ liệu VietDub của tài khoản hiện tại:
   `%LOCALAPPDATA%\VietDub\jobs\<mã job>\run.log` trên Windows (dùng
   `%APPDATA%` nếu `%LOCALAPPDATA%` không có),
   `~/Library/Application Support/VietDub/jobs/<mã job>/run.log` trên macOS,
   hoặc `$XDG_DATA_HOME/VietDub/jobs/<mã job>/run.log` trên Linux
   (mặc định `~/.local/share/VietDub/jobs/<mã job>/run.log`).
3. Tại màn thành phẩm, chọn **Biên tập video** để kéo mép đoạn video cần
   giữ, kéo hoặc chỉnh thời gian và nội dung từng phụ đề, thêm/xóa câu, rồi
   chọn ảnh logo, vị trí, kích thước và độ mờ. Timeline có thanh zoom và
   kéo để tua. Bấm **Xuất video** để tạo MP4 và SRT mới; file cũ được giữ lại.
   Bản nháp biên tập được lưu cùng job. Sửa chữ phụ đề không thay đổi lời
   lồng tiếng đã tổng hợp. Editor có khu xem trước, timeline Video/Dub/Subtitle
   và panel công cụ; khi thu hẹp cửa sổ có thể chuyển giữa xem trước và công cụ.

## Cấu trúc

So sánh ASR trên video thật và các giới hạn của đánh giá nằm trong
[báo cáo benchmark ASR](docs/ASR_BENCHMARK_2026-10-25.md).

```
core/         orchestrator.py (chạy 9 bước), job.py, checkpoint.py,
              settings.py (JSON trong %APPDATA%/VietDub), logger.py
asr/          whisper_adapter.py (Whisper transcript + CAM++ nhãn loa),
              qwen_adapter.py (Qwen + ForcedAligner + CAM++),
              funasr_adapter.py (SenseVoiceSmall/VAD/punc/CAM++)
speaker/      gender.py (pitch -> nam/nữ)
translation/  base.py, openai_api.py, nine_router.py, ollama.py, prompts.py
tts/          edge_tts.py, duration_fit.py (khớp thời lượng)
media/        fetch.py (yt-dlp), extract.py, mix.py, render.py, editor.py,
              thumbnail.py, subs.py
project/      schema.py, io.py
tests/        pytest cho từng module (18 edge cases)
ui/           App PySide6, gồm editor timeline và poster loader nền
```

## Tùy chọn: VietDub STT riêng (local)

Bản thử nghiệm cho phép VietDub gọi engine STT bên ngoài qua giao tiếp HTTP
`http://127.0.0.1:8768/v1/transcribe`. Đây **không phải** backend mặc định:
Whisper + CAM++ vẫn chạy như trước nếu không chọn STT riêng.

1. Tải và cài package `vietdub-stt` riêng (Python 3.10+, FFmpeg,
   `pip install -e '.[qwen,api]'` từ thư mục package).
2. Trong terminal, chạy `python -m vietdub_stt.api`. Dịch vụ chỉ lắng nghe
   trên loopback; lần đầu dùng cần tải weights Qwen và aligner.
3. Trong VietDub → **Cài đặt → Nhận dạng**, chọn
   **VietDub STT riêng (local) + CAM++**. Nhập URL trên, chọn
   **Fast (Qwen 0.6B)** hoặc **Quality (Qwen 1.7B)**.
4. Chạy video với luồng 9 bước hiện tại. Nếu server offline, contract sai hoặc
   timestamp không hợp lệ, VietDub báo lỗi thay vì âm thầm sử dụng transcript
   giả. Người nói chưa xác định được đánh dấu để duyệt thủ công.

STT service xuất JSON schema v1 (`start`, `end`, `text`,
`speaker_id`, `needs_review`). Do bản service MVP chưa tự diarize,
VietDub vẫn dùng CAM++ để gắn speaker, chỉ chấp nhận nhãn có độ phủ
lượt nói đủ lớn và giữ trạng thái cần kiểm duyệt nếu không chắc chắn.
Đây là tích hợp experimental; chưa có kết quả inference + phim thành phẩm
được xác minh với model thật.
