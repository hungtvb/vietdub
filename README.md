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
   python main.py
   ```

### Cách B — build file .exe một lần, chạy mãi mãi (khuyên dùng)

1. Cài Python 3.10+ như cách A, rồi trong cmd tại thư mục VietDub:
   ```
   .venv\Scripts\activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
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

- App tự tải model ASR (~1.3GB) về `%APPDATA%\VietDub\models\` — cần mạng,
  chỉ tải 1 lần duy nhất. Các lần sau chạy offline được (trừ TTS/dịch).
- **Edge-TTS cần mạng** mới lồng được tiếng (giọng Microsoft online).
  Mất mạng giữa chừng → app tự đổi sang gTTS dự phòng (giọng đơn),
  ghi rõ trong log.
- **9Router dùng free-tier** (`mimo-v2.6-flash-free`): cần API key của anh,
  nhập 1 lần ở màn **Cài đặt** → app nhớ mãi. Muốn offline hoàn toàn thì
  dùng Ollama local thay thế (kéo model về trước bằng
  `ollama pull <tên-model>`).

### Dùng app

1. Chọn video (tab File) hoặc dán link Douyin/TikTok/YouTube (tab Link),
   nhấn **Bắt đầu**. Bật **Chế độ qua đêm** nếu muốn máy tự chạy hết
   9 bước không dừng duyệt (sáng dậy có phim).
2. Kết quả: `<tên video>_vidub.mp4` + file `.srt` trong thư mục đã chọn.
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
