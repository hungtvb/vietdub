# VietDub

Desktop app lồng tiếng video tiếng Trung sang tiếng Việt (PySide6).
Pipeline 9 bước: lấy video (file/link) → tách audio → nghe + tách loa
(FunASR) → đoán giới tính bằng pitch → LLM phân tích quan hệ → dịch
(9Router/mimo-v2.6-flash-free hoặc Ollama) → lồng tiếng Edge-TTS
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
```

Cần thêm: **ffmpeg** có trong PATH
([tải tại gyan.dev](https://www.gyan.dev/ffmpeg/builds/) bản Windows,
giải nén rồi thêm `bin` vào PATH).

## Chạy test

```bash
pytest tests/ -v
```

## Hướng dẫn cho người dùng cuối (Windows)

1. Cài Python 3.12 (python.org, tick "Add python.exe to PATH").
2. Tải ffmpeg bản `release essentials`, giải nén, thêm thư mục `bin`
   vào PATH (kiểm tra: mở cmd gõ `ffmpeg -version`).
3. Mở cmd trong thư mục VietDub:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   ```
4. Lần chạy đầu tiên, app tự tải model ASR (~1.3GB) về máy — cần mạng,
   chỉ tải 1 lần.
5. Mở **Cài đặt** → nhập **API key 9Router** (nguồn dịch mặc định, miễn phí),
   hoặc cấu hình Ollama local nếu muốn chạy offline hoàn toàn.
6. Chọn video (tab File) hoặc dán link Douyin/TikTok/YouTube (tab Link),
   nhấn **Bắt đầu**. Bật **Chế độ qua đêm** nếu muốn máy tự chạy hết
   9 bước không dừng duyệt.
7. Kết quả: `<tên video>_vidub.mp4` + file `.srt` trong thư mục đã chọn.
   Log chi tiết từng job nằm ở `jobs/<mã job>/run.log`.

## Cấu trúc

```
core/         orchestrator.py (chạy 9 bước), job.py, checkpoint.py,
              settings.py (JSON trong %APPDATA%/VietDub), logger.py
asr/          funasr_adapter.py (SeacoParaformer + cam++ tách loa)
speaker/      gender.py (pitch -> nam/nữ)
translation/  base.py, nine_router.py, ollama.py, prompts.py
tts/          edge_tts.py, duration_fit.py (khớp thời lượng)
media/        fetch.py (yt-dlp), extract.py, mix.py, render.py, subs.py
project/      schema.py, io.py
tests/        pytest cho từng module (18 edge cases)
ui/           Wave 2 (PySide6)
```
