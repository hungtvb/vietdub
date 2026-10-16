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
# Bắt buộc cho chế độ ASR tự động/Whisper + pyannote:
pip install -r requirements-asr-hybrid.txt
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
   pip install -r requirements-asr-hybrid.txt
   python main.py
   ```

### Cách B — build file .exe một lần, chạy mãi mãi (khuyên dùng)

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
