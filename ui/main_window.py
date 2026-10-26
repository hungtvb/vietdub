# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Màn 1 - Màn hình chính: chọn video (tab File / tab Link) + tùy chọn nhanh.

- Tab File: nút chọn video + kéo-thả, hiện info (tên, thời lượng, phân giải).
- Tab Link: ô paste link + nút [Tải về] (tiến trình % + tốc độ) -> xong hiện
  info video, lúc đó mới cho [Bắt đầu].
- Tùy chọn nhanh: giọng nam/nữ (dropdown + [Nghe thử]), nguồn dịch,
  dropdown track audio (hiện khi video có > 1 track), tick dừng duyệt,
  tick chế độ qua đêm, thư mục lưu, nút [Bắt đầu].
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QProgressBar,
                               QPushButton, QScrollArea, QSizePolicy,
                               QTabWidget, QVBoxLayout, QWidget)

from core.job import Job
from core.settings import Settings
from media import _bin as mbin
from ui.common import confirm_box, error_box, fmt_time
from ui.theme import APP_BACKGROUND, UI_COLORS

VIDEO_FILTER = ("Video (*.mp4 *.mkv *.avi *.mov *.webm *.ts *.m4v);;"
                "Tất cả (*.*)")


class DropLabel(QLabel):
    """Vùng kéo-thả file video. Phát signal khi có file thả vào."""
    file_dropped = Signal(str)

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(96)

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:  # noqa: N802
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.file_dropped.emit(path)
                break
        e.acceptProposedAction()


class DownloadWorker(QObject):
    """Tải video từ link trong thread riêng (không đơ UI)."""
    progressed = Signal(float, str)   # pct, speed
    finished = Signal(str)            # dest path
    failed = Signal(str)              # thông báo lỗi tiếng Việt

    def __init__(self, url: str, job: Job):
        super().__init__()
        self.url = url
        self.job = job

    def run(self) -> None:
        try:
            from media import fetch as mfetch
            path = mfetch.resolve(
                self.url, self.job.job_dir,
                progress_cb=lambda p, s: self.progressed.emit(p, s))
            self.finished.emit(str(path))
        except Exception as e:  # noqa: BLE001 - FetchError đã là tiếng Việt
            self.failed.emit(str(e))


class VoicePreviewWorker(QObject):
    """Tạo câu mẫu bằng TTS provider đang chọn trong thread riêng."""
    done = Signal(str)     # wav path
    failed = Signal(str)   # thông báo lỗi

    def __init__(self, voice: str, gender: str, tmpdir: Path,
                 provider: str, settings: Settings):
        super().__init__()
        self.voice = voice
        self.gender = gender
        self.tmpdir = tmpdir
        self.provider = provider
        self.settings = settings

    def run(self) -> None:
        try:
            from project.schema import Segment
            from tts.provider import create_tts
            seg = Segment(index=0, start=0.0, end=6.0, speaker=0,
                          gender=self.gender,
                          text_vi="Xin chào, đây là giọng lồng tiếng của VietDub.")
            tts = create_tts(self.settings, provider=self.provider,
                             voice_male=self.voice, voice_female=self.voice)
            tts.synthesize([seg], self.tmpdir)
            if seg.audio_vi:
                self.done.emit(seg.audio_vi)
            else:
                self.failed.emit("Không tạo được file giọng mẫu.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class VideoInfoWorker(QObject):
    """Đọc một lần bằng ffprobe ngoài luồng giao diện."""
    finished = Signal(str, dict)
    failed = Signal(str, str)
    completed = Signal()

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.ffprobe = mbin.ffprobe_cmd()

    @Slot()
    def run(self) -> None:
        import json
        import subprocess
        try:
            result = subprocess.run(
                [self.ffprobe, "-v", "error", "-print_format", "json",
                 "-show_streams", "-show_format", self.path],
                capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise ValueError("Tệp video bị hỏng hoặc định dạng không được hỗ trợ.")
            data = json.loads(result.stdout or "{}")
            streams = data.get("streams", [])
            video = next((st for st in streams
                          if st.get("codec_type") == "video"), None)
            audio = [st for st in streams if st.get("codec_type") == "audio"]
            if not video:
                raise ValueError("Tệp này không có hình ảnh video hợp lệ.")
            if not audio:
                raise ValueError("Video không có âm thanh để nhận dạng và lồng tiếng.")
            try:
                duration = float(data.get("format", {}).get("duration", 0) or 0)
            except (ValueError, TypeError):
                duration = 0.0
            width, height = video.get("width"), video.get("height")
            self.finished.emit(self.path, {
                "audio": audio, "duration": duration,
                "resolution": f"{width}×{height}" if width and height else "—"})
        except subprocess.TimeoutExpired:
            self.failed.emit(self.path, "Đọc thông tin video quá 30 giây.")
        except OSError:
            self.failed.emit(self.path, "Không chạy được công cụ đọc video ffprobe.")
        except json.JSONDecodeError:
            self.failed.emit(self.path, "Công cụ đọc video trả về thông tin không hợp lệ.")
        except ValueError as exc:
            self.failed.emit(self.path, str(exc))
        except Exception:  # noqa: BLE001 - luôn khép lại vòng đời worker
            self.failed.emit(self.path, "Không kiểm tra được thông tin video.")
        finally:
            self.completed.emit()


class _VideoInfoRequest(QObject):
    """Nhận kết quả trên luồng UI; token phân biệt cả lần chọn lại cùng tệp."""
    def __init__(self, window, generation: int, target: dict, url: str):
        super().__init__(window)
        self.generation = generation
        self.target = target
        self.url = url

    @Slot(str, dict)
    def ready(self, path: str, data: dict) -> None:
        window = self.parent()
        if (self.generation == window._source_generation
                and not window._close_when_idle):
            window._show_info(self.target, path, data, self.url)

    @Slot(str, str)
    def failed(self, path: str, message: str) -> None:
        window = self.parent()
        if (self.generation == window._source_generation
                and not window._close_when_idle):
            window._source_feedback(
                f"{message} Chọn video khác hoặc kiểm tra FFmpeg trong Cài đặt.",
                "danger")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        mbin.configure(self.settings.get("ffmpeg_path"))
        self.setWindowTitle("VietDub — Lồng tiếng video Trung sang Việt")
        self.setStyleSheet(f"QWidget#appRoot, QWidget#mainShell {{ background: {APP_BACKGROUND}; }}")
        self.resize(800, 790)
        self.setMinimumSize(620, 500)

        self.job: Job | None = None          # tạo khi cần (tải link / bắt đầu)
        self.video_path: str = ""            # file local sẵn sàng xử lý
        self.video_url: str = ""             # link đã tải xong
        self._dl_thread: QThread | None = None
        self._dl_worker = None
        self._pv_thread: QThread | None = None
        self._pv_worker = None
        self._pv_tmps: list = []          # thư mục tạm của [Nghe thử]
        self._progress_win = None
        self._batch_window = None
        self._tasks: dict[QThread, tuple] = {}
        self._source_generation = 0
        self._active_info = None
        self._close_when_idle = False
        self._preview_buttons: list[QPushButton] = []

        # Khởi tạo audio engine khi người dùng nghe thử, không phải lúc mở app.
        # Một số máy không có audio backend khả dụng; điều đó không nên chặn UI.
        self._player: QMediaPlayer | None = None
        self._audio_out: QAudioOutput | None = None

        shell = QWidget()
        shell.setObjectName("mainShell")
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)
        self.setCentralWidget(shell)
        page = self.page = QScrollArea()
        page.setWidgetResizable(True)
        page.setFrameShape(QFrame.NoFrame)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        shell_lay.addWidget(page, 1)
        central = QWidget()
        central.setObjectName("appRoot")
        page.setWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 20)
        root.setSpacing(16)

        header_card = QFrame()
        header_card.setObjectName("mainHeader")
        head = QHBoxLayout(header_card)
        head.setContentsMargins(15, 10, 15, 10)
        mark = QLabel("VD")
        mark.setObjectName("mainMark")
        mark.setFixedSize(34, 34)
        mark.setAlignment(Qt.AlignCenter)
        head.addWidget(mark)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(0)
        title = QLabel("VietDub")
        title.setObjectName("appTitle")
        subtitle = QLabel("Studio lồng tiếng Việt")
        subtitle.setObjectName("appSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        head.addLayout(title_stack)
        head.addStretch(1)
        self.btn_settings = QPushButton("Cài đặt")
        self.btn_settings.setProperty("role", "secondary")
        self.btn_settings.clicked.connect(self.open_settings)
        head.addWidget(self.btn_settings)
        root.addWidget(header_card)

        intro = QLabel("Chọn video để bắt đầu")
        intro.setObjectName("pageTitle")
        intro.setWordWrap(True)
        root.addWidget(intro)

        source_card = QFrame()
        source_card.setObjectName("mainCard")
        source_lay = QVBoxLayout(source_card)
        source_lay.setContentsMargins(15, 12, 15, 12)
        source_title = QLabel("Nguồn video")
        source_title.setObjectName("sectionTitle")
        source_lay.addWidget(source_title)
        self.tabs = QTabWidget()
        source_lay.addWidget(self.tabs)
        root.addWidget(source_card)
        self._build_file_tab()
        self._build_link_tab()
        self.source_detail = QLabel("Chọn video có âm thanh để nhận dạng lời thoại.")
        self.source_detail.setWordWrap(True)
        self.source_detail.setTextFormat(Qt.PlainText)
        self.source_detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.source_detail.setProperty("role", "secondary")
        source_lay.addWidget(self.source_detail)

        self.options_toggle = QPushButton("Tùy chọn lồng tiếng…")
        self.options_toggle.setCheckable(True)
        self.options_toggle.setProperty("role", "secondary")
        self.options_toggle.setToolTip("Giọng đọc, nguồn dịch, duyệt phụ đề và thư mục lưu")
        root.addWidget(self.options_toggle)
        self.options_box = self._build_options_group()
        self.options_box.setVisible(False)
        self.options_toggle.toggled.connect(self.options_box.setVisible)
        root.addWidget(self.options_box)
        root.addStretch(1)

        footer = QFrame()
        footer.setObjectName("mainFooter")
        self.footer_lay = QBoxLayout(QBoxLayout.LeftToRight, footer)
        footer_lay = self.footer_lay
        footer_lay.setContentsMargins(24, 10, 24, 10)
        self.source_status = QLabel("Chưa chọn video")
        self.source_status.setObjectName("mainSourceStatus")
        self.source_status.setWordWrap(True)
        self.source_status.setTextFormat(Qt.PlainText)
        self.source_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        footer_lay.addWidget(self.source_status, 1)
        self.btn_batch = QPushButton("Hàng đợi")
        self.btn_batch.setProperty("role", "secondary")
        self.btn_batch.clicked.connect(self.open_batch_queue)
        footer_lay.addWidget(self.btn_batch)
        self.btn_start = QPushButton("Bắt đầu lồng tiếng")
        self.btn_start.setMinimumHeight(48)
        self.btn_start.setMinimumWidth(200)
        self.btn_start.setProperty("role", "primary")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_job)
        footer_lay.addWidget(self.btn_start)
        shell_lay.addWidget(footer)
        self._resize_footer()

    # ------------------------------------------------------------------ tab
    def _build_file_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 10, 4, 8)
        lay.setSpacing(12)
        self.drop = DropLabel("Kéo-thả file video vào đây\n"
                              "hoặc bấm nút bên dưới để chọn file")
        self.drop.setObjectName("dropZone")
        self.drop.file_dropped.connect(self.pick_video_file)
        lay.addWidget(self.drop)
        btn = QPushButton("Chọn video…")
        btn.setProperty("role", "secondary")
        btn.clicked.connect(lambda: self.pick_video_file(""))
        lay.addWidget(btn)
        self.file_info = self._info_group()
        lay.addWidget(self.file_info["box"])
        lay.addStretch(1)
        self.tabs.addTab(tab, "Tệp video")

    def _build_link_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(4, 10, 4, 8)
        lay.setSpacing(12)
        lay.addWidget(QLabel("Dán link video (Douyin / TikTok / YouTube / …):"))
        row = QHBoxLayout()
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("https://…")
        row.addWidget(self.link_edit, 1)
        self.btn_download = QPushButton("Tải về")
        self.btn_download.setProperty("role", "primary")
        self.btn_download.clicked.connect(self.download_link)
        row.addWidget(self.btn_download)
        lay.addLayout(row)
        dl_row = QHBoxLayout()
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        self.dl_bar.setTextVisible(False)
        dl_row.addWidget(self.dl_bar, 1)
        self.dl_speed = QLabel("")
        dl_row.addWidget(self.dl_speed)
        lay.addLayout(dl_row)
        self.link_info = self._info_group()
        lay.addWidget(self.link_info["box"])
        lay.addStretch(1)
        self.tabs.addTab(tab, "Liên kết")

    def _info_group(self) -> dict:
        """Cụm hiện info video dùng chung cho 2 tab."""
        box = QGroupBox("Thông tin video")
        form = QFormLayout(box)
        name = QLabel("—")
        name.setWordWrap(True)
        name.setTextFormat(Qt.PlainText)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        dur = QLabel("—")
        res = QLabel("—")
        form.addRow("Tên file:", name)
        form.addRow("Thời lượng:", dur)
        form.addRow("Phân giải:", res)
        track_row_widget = QWidget()
        track_row_lay = QHBoxLayout(track_row_widget)
        track_row_lay.setContentsMargins(0, 0, 0, 0)
        track_label = QLabel("Rãnh âm thanh:")
        track = QComboBox()
        track.setMinimumContentsLength(12)
        track.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        track_row_lay.addWidget(track_label)
        track_row_lay.addWidget(track, 1)
        form.addRow(track_row_widget)
        box.setVisible(False)
        return {"box": box, "name": name, "dur": dur, "res": res,
                "track": track, "track_row": track_row_widget}

    def _source_feedback(self, message: str, state: str = "secondary_text") -> None:
        self.source_status.setText(
            "Video chưa sẵn sàng · xem hướng dẫn ở nguồn video" if state == "danger" else message)
        self.source_status.setStyleSheet(f"color: {UI_COLORS[state]};")
        self.source_status.setToolTip(message)
        self.source_detail.setText(message)
        self.source_detail.setStyleSheet(f"color: {UI_COLORS[state]};")
        if not self._close_when_idle:
            QTimer.singleShot(30, self._reveal_source_feedback)

    @Slot()
    def _reveal_source_feedback(self) -> None:
        self.page.ensureWidgetVisible(self.source_detail, 0, 12)

    def _clear_source(self, message: str) -> int:
        self._source_generation += 1
        self.video_path = ""
        self.video_url = ""
        self._active_info = None
        self.btn_start.setEnabled(False)
        self.file_info["box"].hide()
        self.link_info["box"].hide()
        self._source_feedback(message)
        return self._source_generation

    def _probe_video(self, target: dict, path: str, url: str = "",
                     generation: int | None = None) -> None:
        if generation is None:
            generation = self._clear_source("Đang kiểm tra video…")
        if generation != self._source_generation:
            return
        self._source_feedback("Đang kiểm tra video…")
        worker = VideoInfoWorker(path)
        receiver = _VideoInfoRequest(self, generation, target, url)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(receiver.ready)
        worker.failed.connect(receiver.failed)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        self._retain_task(thread, worker, receiver)
        thread.start()

    def _show_info(self, info: dict, path: str, data: dict, url: str = "") -> None:
        self.video_path, self.video_url = path, url
        self._active_info = info
        info["name"].setText(Path(path).name)
        info["name"].setToolTip(path)
        self._source_feedback("Sẵn sàng lồng tiếng", "success")
        self.source_status.setToolTip(path)
        info["dur"].setText(fmt_time(data["duration"]))
        info["res"].setText(data["resolution"])
        combo: QComboBox = info["track"]
        combo.clear()
        for i, st in enumerate(data["audio"]):
            lang = st.get("tags", {}).get("language", "")
            channels = st.get("channels", "?")
            codec = st.get("codec_name", "")
            label = f"Rãnh {i + 1} — {codec}, {channels} kênh"
            combo.addItem(label + (f" ({lang})" if lang else ""), i)
        info["track_row"].setVisible(len(data["audio"]) > 1)
        combo.setCurrentIndex(0)
        info["box"].show()
        self.btn_start.setEnabled(not self._close_when_idle)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "footer_lay"):
            self._resize_footer()

    def _resize_footer(self) -> None:
        compact = self.width() < 760
        self.footer_lay.setDirection(
            QBoxLayout.TopToBottom if compact else QBoxLayout.LeftToRight)

    def _retain_task(self, thread: QThread, worker: QObject,
                     receiver: QObject | None = None) -> None:
        self._tasks[thread] = (worker, receiver)
        thread.finished.connect(self._task_finished)

    @Slot()
    def _task_finished(self) -> None:
        thread = self.sender()
        _, receiver = self._tasks.pop(thread, (None, None))
        if receiver is not None:
            receiver.deleteLater()
        if thread is self._dl_thread:
            self._dl_worker = self._dl_thread = None
            self.btn_download.setEnabled(True)
        if thread is self._pv_thread:
            self._pv_worker = self._pv_thread = None
            for button in self._preview_buttons:
                button.setEnabled(True)
            self._preview_button.setText("Nghe thử")
        thread.deleteLater()
        if self._close_when_idle and not self._tasks:
            self.close()

    # -------------------------------------------------------------- tab File
    def pick_video_file(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Chọn video", "", VIDEO_FILTER)
        if not path:
            return
        if not Path(path).is_file():
            self._clear_source("Chưa chọn được video")
            self._source_feedback("Tệp không tồn tại hoặc không phải là tệp video. "
                                  "Bấm Chọn video để chọn một tệp khác.", "danger")
            return
        self.tabs.setCurrentIndex(0)
        self._probe_video(self.file_info, path)

    # -------------------------------------------------------------- tab Link
    def _ensure_job(self) -> Job:
        if self.job is None:
            self.job = Job()
        return self.job

    def download_link(self) -> None:
        url = self.link_edit.text().strip()
        if not url:
            error_box(self, "Chưa có link",
                      "Hãy dán link video vào ô trước khi bấm Tải về.")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            error_box(self, "Link không hợp lệ",
                      "Link phải bắt đầu bằng http:// hoặc https://.")
            return
        if self._dl_thread is not None:
            return
        self._download_url = url
        self._download_generation = self._clear_source("Đang tải video…")
        self.btn_download.setEnabled(False)
        self.dl_bar.setValue(0)
        self.dl_speed.setText("Đang tải…")
        job = self._ensure_job()
        worker = DownloadWorker(url, job)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.progressed.connect(self._on_dl_progress)
        worker.finished.connect(self._on_dl_finished)
        worker.failed.connect(self._on_dl_failed)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        # finished/failed phát trong worker thread khi loop còn sống ->
        # deleteLater được xử lý ngay, không leak worker mỗi lần tải.
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._retain_task(thread, worker)
        # GIỮ reference: không giữ -> Python GC worker -> run() không chạy
        self._dl_worker = worker
        self._dl_thread = thread
        thread.start()

    @Slot(float, str)
    def _on_dl_progress(self, pct: float, speed: str) -> None:
        self.dl_bar.setValue(int(pct))
        self.dl_speed.setText(f"{pct:.0f}% {speed}".strip())

    @Slot(str)
    def _on_dl_finished(self, path: str) -> None:
        self.dl_bar.setValue(100)
        self.dl_speed.setText("Đã tải xong")
        if (self._download_generation == self._source_generation
                and not self._close_when_idle):
            self._probe_video(self.link_info, path, self._download_url,
                              self._download_generation)

    @Slot(str)
    def _on_dl_failed(self, message: str) -> None:
        self.dl_bar.setValue(0)
        self.dl_speed.setText("Tải lỗi · sửa liên kết và thử lại")
        if (self._download_generation == self._source_generation
                and not self._close_when_idle):
            self._source_feedback(f"Tải thất bại: {message}. Kiểm tra liên kết rồi tải lại.",
                                  "danger")

    # --------------------------------------------------------------- tùy chọn
    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("Tùy chọn lồng tiếng")
        lay = QVBoxLayout(box)

        # Engine is independent of the LLM translation provider.
        self.tts_provider = QComboBox()
        self.tts_provider.addItem("Edge-TTS (online)", "edge")
        self.tts_provider.addItem("VieNeu v3 Turbo (offline)", "vieneu")
        self._voice_drafts = {
            "edge": (self.settings.get("voice_male"),
                     self.settings.get("voice_female")),
            "vieneu": (self.settings.get("vieneu_voice_male", "Hải Đăng"),
                       self.settings.get("vieneu_voice_female", "Mai Anh")),
        }
        self._active_tts_provider = None
        vg = QFormLayout()
        vg.addRow("Công nghệ TTS:", self.tts_provider)
        vg.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self.voice_male = QComboBox()
        self.voice_male.setEditable(True)
        self.voice_male.setMinimumContentsLength(12)
        self.voice_male.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.voice_female = QComboBox()
        self.voice_female.setEditable(True)
        self.voice_female.setMinimumContentsLength(12)
        self.voice_female.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for cb, default in ((self.voice_male, self.settings.get("voice_male")),
                            (self.voice_female, self.settings.get("voice_female"))):
            cb.addItem(default)
            cb.setCurrentText(default)
        self.tts_provider.setCurrentIndex(max(
            0, self.tts_provider.findData(self.settings.get("tts_provider", "edge"))))
        self.tts_provider.currentIndexChanged.connect(self._on_tts_provider_changed)
        self._on_tts_provider_changed()
        row_m = QHBoxLayout()
        row_m.addWidget(self.voice_male, 1)
        btn_pm = QPushButton("Nghe thử")
        btn_pm.clicked.connect(lambda: self.preview_voice(
            self.voice_male.currentText().strip(), "male", btn_pm))
        row_m.addWidget(btn_pm)
        self._preview_buttons.append(btn_pm)
        row_f = QHBoxLayout()
        row_f.addWidget(self.voice_female, 1)
        btn_pf = QPushButton("Nghe thử")
        btn_pf.clicked.connect(lambda: self.preview_voice(
            self.voice_female.currentText().strip(), "female", btn_pf))
        row_f.addWidget(btn_pf)
        self._preview_buttons.append(btn_pf)
        vg.addRow("Giọng nam:", row_m)
        vg.addRow("Giọng nữ:", row_f)
        lay.addLayout(vg)

        self.provider = QComboBox()
        self.provider.addItem("OpenAI GPT (khuyên dùng)", "openai")
        self.provider.addItem("9Router", "9router")
        self.provider.addItem("Ollama (trên máy)", "ollama")
        cur = self.settings.get("translate_provider", "openai")
        self.provider.setCurrentIndex(max(0, self.provider.findData(cur)))
        pf = QFormLayout()
        pf.addRow("Nguồn dịch:", self.provider)
        lay.addLayout(pf)

        self.chk_review = QCheckBox("Dừng để duyệt phụ đề và bản dịch")
        self.chk_review.setChecked(bool(self.settings.get("review_stops", True)))
        self.chk_overnight = QCheckBox("Chế độ qua đêm (chạy liên tục)")
        self.chk_overnight.setToolTip(
            "Chạy liền 9 bước và tự bỏ qua điểm dừng duyệt.")
        self.chk_overnight.setChecked(bool(self.settings.get("overnight", False)))
        self.chk_overnight.toggled.connect(self._on_overnight_toggled)
        lay.addWidget(self.chk_review)
        lay.addWidget(self.chk_overnight)
        self._on_overnight_toggled(self.chk_overnight.isChecked())

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Thư mục lưu:"))
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText("Để trống = lưu cạnh file video gốc")
        out_row.addWidget(self.out_dir, 1)
        btn_out = QPushButton("Chọn…")
        btn_out.clicked.connect(self.choose_out_dir)
        out_row.addWidget(btn_out)
        lay.addLayout(out_row)
        return box

    def _on_tts_provider_changed(self, _index=None) -> None:
        """Keep distinct per-provider voices when switching without losing edits."""
        previous = self._active_tts_provider
        if previous:
            self._voice_drafts[previous] = (
                self.voice_male.currentText().strip(),
                self.voice_female.currentText().strip())
        current = self.tts_provider.currentData() or "edge"
        male, female = self._voice_drafts[current]
        self.voice_male.setCurrentText(male)
        self.voice_female.setCurrentText(female)
        self._active_tts_provider = current

    def _on_overnight_toggled(self, on: bool) -> None:
        # Chế độ qua đêm CẤM treo chờ người -> tự tắt dừng duyệt (DESIGN).
        if on:
            self.chk_review.setChecked(False)
            self.chk_review.setEnabled(False)
            self.chk_review.setToolTip("Chế độ qua đêm tự tắt điểm dừng duyệt "
                                       "để máy không treo chờ giữa đêm.")
        else:
            self.chk_review.setEnabled(True)
            self.chk_review.setToolTip("")
            # khôi phục lựa chọn dừng duyệt đã lưu (mặc định bật)
            self.chk_review.setChecked(
                bool(self.settings.get("review_stops", True)))

    def choose_out_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video")
        if d:
            self.out_dir.setText(d)

    def preview_voice(self, voice: str, gender: str, btn: QPushButton) -> None:
        if not voice:
            error_box(self, "Chưa chọn giọng",
                      "Hãy chọn hoặc nhập mã giọng (vd vi-VN-NamMinhNeural).")
            return
        if self._pv_thread is not None:
            return
        self._preview_button = btn
        for button in self._preview_buttons:
            button.setEnabled(False)
        btn.setText("Đang tạo…")
        # Thư mục tạm riêng cho giọng mẫu: không tạo thư mục job mồ côi
        # (jobs/<id>/) trên đĩa khi user chỉ bấm [Nghe thử] mà chưa bao giờ
        # bắt đầu job thật. Giữ reference tới khi đóng app.
        tmp = tempfile.TemporaryDirectory(prefix="vietdub_nghe_thu_")
        self._pv_tmps.append(tmp)
        tmpdir = Path(tmp.name)
        worker = VoicePreviewWorker(
            voice, gender, tmpdir, self.tts_provider.currentData(), self.settings)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.done.connect(self._on_preview_done)
        worker.failed.connect(self._on_preview_failed)
        thread.started.connect(worker.run)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        # done/failed phát trong worker thread khi loop còn sống ->
        # deleteLater được xử lý ngay, không leak worker mỗi lần nghe thử.
        worker.done.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self._retain_task(thread, worker)
        # GIỮ reference: không giữ -> Python GC worker -> run() không chạy
        self._pv_worker = worker
        self._pv_thread = thread
        thread.start()

    @Slot(str)
    def _on_preview_done(self, wav: str) -> None:
        if self._close_when_idle:
            return
        if self._player is None:
            self._player = QMediaPlayer(self)
            if QGuiApplication.platformName() != "offscreen":
                self._audio_out = QAudioOutput(self)
                self._player.setAudioOutput(self._audio_out)
        self._player.setSource(QUrl.fromLocalFile(wav))
        self._player.play()

    @Slot(str)
    def _on_preview_failed(self, message: str) -> None:
        if self._close_when_idle:
            return
        hint = ("Cài VieNeu bằng: pip install -r requirements-vieneu.txt "
                "và kiểm tra backend/model." if self.tts_provider.currentData() == "vieneu"
                else "Kiểm tra kết nối Microsoft Edge-TTS.")
        error_box(self, "Không nghe thử được", f"{message}\n\n{hint}")

    # ------------------------------------------------------------------ bắt đầu
    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        if open_settings_dialog(self, self.settings):
            # settings đã được lưu trong dialog; áp lại vào UI chính
            self._voice_drafts = {
                "edge": (self.settings.get("voice_male"),
                         self.settings.get("voice_female")),
                "vieneu": (self.settings.get("vieneu_voice_male"),
                           self.settings.get("vieneu_voice_female")),
            }
            self._active_tts_provider = None
            selected = self.settings.get("tts_provider", "edge")
            self.tts_provider.setCurrentIndex(max(
                0, self.tts_provider.findData(selected)))
            self._on_tts_provider_changed()
            cur = self.settings.get("translate_provider", "openai")
            self.provider.setCurrentIndex(max(0, self.provider.findData(cur)))
            self.chk_review.setChecked(bool(self.settings.get("review_stops", True)))
            self.chk_overnight.setChecked(bool(self.settings.get("overnight", False)))

    def _transient_workers_running(self) -> bool:
        return bool(self._tasks)

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._transient_workers_running():
            self._close_when_idle = True
            self.btn_start.setEnabled(False)
            self.centralWidget().setEnabled(False)
            self._source_feedback("Đang hoàn tất tác vụ nền trước khi đóng…")
            e.ignore()
            return

        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        # Dọn thư mục tạm của [Nghe thử] khi đóng app.
        for tmp in self._pv_tmps:
            try:
                tmp.cleanup()
            except Exception:  # noqa: BLE001
                pass
        self._pv_tmps.clear()
        super().closeEvent(e)

    def _audio_track_index(self) -> int:
        info = self._active_info
        if info is not None and info["track"].count() > 1:
            return int(info["track"].currentData() or 0)
        return 0

    def start_job(self) -> None:
        if (not self.btn_start.isEnabled() or not self.video_path
                or not Path(self.video_path).is_file()):
            error_box(self, "Chưa có video",
                      "Hãy chọn file video (Tệp video) hoặc tải video từ liên kết "
                      "(tab Liên kết) trước khi bắt đầu.")
            return
        if not self._validate_provider_choice():
            return

        job = self._ensure_job()
        self._configure_job(job, self.video_path, video_url=self.video_url,
                            audio_track=self._audio_track_index())

        from ui.progress import ProgressWindow
        self._progress_win = ProgressWindow(job, self.settings,
                                            on_close=self._back_to_main)
        self._progress_win.show()
        self.hide()
        self._progress_win.begin()

    def _validate_provider_choice(self, parent=None) -> bool:
        """Validate the selected translator before starting one or more jobs."""
        parent = parent or self
        provider = self.provider.currentData()
        if provider == "openai" and not self.settings.get("openai_api_key"):
            error_box(parent, "Chưa nhập OpenAI API key",
                      "Mở Cài đặt → tab Dịch thuật để nhập OpenAI API key. "
                      "API tính phí riêng, không dùng chung gói ChatGPT.")
            return False
        if provider == "9router" and not self.settings.get("nine_router_key"):
            if not confirm_box(
                    parent, "Chưa nhập API key 9Router",
                    "Bạn chưa nhập API key 9Router trong Cài đặt.\n"
                    "Vẫn bắt đầu? (bước dịch có thể lỗi, hoặc tự chuyển "
                    "sang Ollama nếu đã cấu hình)"):
                return False
        if provider == "ollama" and not self.settings.get("ollama_model"):
            error_box(parent, "Chưa cấu hình Ollama",
                      "Bạn chọn nguồn dịch Ollama nhưng chưa nhập tên model "
                      "trong Cài đặt.\n\nCách khắc phục: mở Cài đặt → tab Dịch "
                      "thuật → nhập tên model (vd llama3.1) rồi bấm Lưu.")
            return False
        return True

    def _configure_job(self, job: Job, video_path: str, *, video_url: str = "",
                       audio_track: int = 0) -> Job:
        """Snapshot the current quick options into one independent job."""
        provider = self.provider.currentData()
        proj = job.project
        proj.name = Path(video_path).stem
        if video_url:
            proj.video_source = "url"
            proj.video_url = video_url
            proj.video_in = video_path  # file đã tải (fetch sẽ dùng lại)
        else:
            proj.video_source = "file"
            proj.video_url = ""
            proj.video_in = video_path
        out_dir = self.out_dir.text().strip()
        if out_dir:
            out_name = Path(video_path).stem + "_vidub.mp4"
            proj.video_out = str(Path(out_dir) / out_name)
        else:
            proj.video_out = ""
        tts_provider = self.tts_provider.currentData() or "edge"
        proj.tts_provider = tts_provider
        proj.vieneu_backend = self.settings.get("vieneu_backend", "auto")
        proj.vieneu_precision = self.settings.get("vieneu_precision", "fp32")
        proj.tts_rate = self.settings.get("tts_rate", "+0%")
        proj.tts_pitch = self.settings.get("tts_pitch", "+0Hz")
        male_key = "vieneu_voice_male" if tts_provider == "vieneu" else "voice_male"
        female_key = "vieneu_voice_female" if tts_provider == "vieneu" else "voice_female"
        proj.voice_male = self.voice_male.currentText().strip() \
            or self.settings.get(male_key)
        proj.voice_female = self.voice_female.currentText().strip() \
            or self.settings.get(female_key)
        proj.translate_provider = provider
        proj.review_stops = self.chk_review.isChecked()
        proj.overnight = self.chk_overnight.isChecked()
        proj.audio_track = int(audio_track)
        proj.proper_nouns = list(self.settings.get("proper_nouns", []))

        # lưu lựa chọn nhanh vào settings để mở lại app vẫn giữ
        self._voice_drafts[tts_provider] = (proj.voice_male, proj.voice_female)
        for key_provider, (male, female) in self._voice_drafts.items():
            prefix = "vieneu_" if key_provider == "vieneu" else ""
            self.settings.set(prefix + "voice_male", male)
            self.settings.set(prefix + "voice_female", female)
        self.settings.set("tts_provider", tts_provider)
        self.settings.set("translate_provider", provider)
        self.settings.set("review_stops", proj.review_stops)
        self.settings.set("overnight", proj.overnight)
        self.settings.save()

        from project import io as pio
        pio.save_project(job.job_dir, proj)
        return job

    def create_batch_job(self, video_path: str) -> Job:
        """Create a new local-file job using the current quick options."""
        return self._configure_job(Job(), video_path, audio_track=0)

    def open_batch_queue(self) -> None:
        from ui.batch_queue import BatchQueueWindow
        if self._batch_window is not None and self._batch_window.isVisible():
            self._batch_window.raise_()
            self._batch_window.activateWindow()
            return
        self._batch_window = BatchQueueWindow(
            self, self.settings, on_close=self._batch_queue_closed)
        self._batch_window.show()
        self.hide()

    def _batch_queue_closed(self) -> None:
        self._batch_window = None
        self.show()

    def _back_to_main(self) -> None:
        self.job = None
        self._clear_source("Chưa chọn video")
        self.file_info["box"].setVisible(False)
        self.link_info["box"].setVisible(False)
        self.dl_bar.setValue(0)
        self.dl_speed.setText("")
        self.show()
