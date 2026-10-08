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

from PySide6.QtCore import QObject, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QProgressBar, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from core.job import Job
from core.settings import Settings
from media import _bin as mbin
from project.schema import Project
from ui.common import confirm_box, error_box, fmt_size, fmt_time, info_box

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
        self.setMinimumHeight(110)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #7f8c8d; border-radius: 8px;"
            " background: #f4f6f7; color: #2c3e50; font-size: 13px;"
            " padding: 18px; }")

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
        from media import fetch as mfetch
        try:
            path = mfetch.resolve(
                self.url, self.job.job_dir,
                progress_cb=lambda p, s: self.progressed.emit(p, s))
            self.finished.emit(str(path))
        except Exception as e:  # noqa: BLE001 - FetchError đã là tiếng Việt
            self.failed.emit(str(e))


class VoicePreviewWorker(QObject):
    """Tạo câu mẫu bằng Edge-TTS trong thread riêng."""
    done = Signal(str)     # wav path
    failed = Signal(str)   # thông báo lỗi

    def __init__(self, voice: str, gender: str, tmpdir: Path):
        super().__init__()
        self.voice = voice
        self.gender = gender
        self.tmpdir = tmpdir

    def run(self) -> None:
        from project.schema import Segment
        from tts.edge_tts import EdgeTTS
        seg = Segment(index=0, start=0.0, end=6.0, speaker=0,
                      gender=self.gender,
                      text_vi="Xin chào, đây là giọng lồng tiếng của VietDub.")
        try:
            tts = EdgeTTS(voice_male=self.voice, voice_female=self.voice)
            tts.synthesize([seg], self.tmpdir)
            if seg.audio_vi:
                self.done.emit(seg.audio_vi)
            else:
                self.failed.emit("Không tạo được file giọng mẫu.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings()
        mbin.configure(self.settings.get("ffmpeg_path"))
        self.setWindowTitle("VietDub — Lồng tiếng video Trung sang Việt")
        self.resize(640, 720)

        self.job: Job | None = None          # tạo khi cần (tải link / bắt đầu)
        self.video_path: str = ""            # file local sẵn sàng xử lý
        self.video_url: str = ""             # link đã tải xong
        self._dl_thread: QThread | None = None
        self._dl_worker = None
        self._pv_thread: QThread | None = None
        self._pv_worker = None
        self._pv_tmps: list = []          # thư mục tạm của [Nghe thử]
        self._progress_win = None

        # audio phát giọng mẫu
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        head = QHBoxLayout()
        title = QLabel("VietDub")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        head.addWidget(title)
        head.addStretch(1)
        self.btn_settings = QPushButton("Cài đặt")
        self.btn_settings.clicked.connect(self.open_settings)
        head.addWidget(self.btn_settings)
        root.addLayout(head)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self._build_file_tab()
        self._build_link_tab()

        root.addWidget(self._build_options_group())

        self.btn_start = QPushButton("Bắt đầu lồng tiếng")
        self.btn_start.setMinimumHeight(44)
        self.btn_start.setStyleSheet(
            "QPushButton { font-size: 15px; font-weight: bold;"
            " background: #27ae60; color: white; border-radius: 6px; }"
            "QPushButton:disabled { background: #bdc3c7; }")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.start_job)
        root.addWidget(self.btn_start)

    # ------------------------------------------------------------------ tab
    def _build_file_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        self.drop = DropLabel("Kéo-thả file video vào đây\n"
                              "hoặc bấm nút bên dưới để chọn file")
        self.drop.file_dropped.connect(self.pick_video_file)
        lay.addWidget(self.drop)
        btn = QPushButton("Chọn video…")
        btn.clicked.connect(lambda: self.pick_video_file(""))
        lay.addWidget(btn)
        self.file_info = self._info_group()
        lay.addWidget(self.file_info["box"])
        lay.addStretch(1)
        self.tabs.addTab(tab, "File")

    def _build_link_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(QLabel("Dán link video (Douyin / TikTok / YouTube / …):"))
        row = QHBoxLayout()
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("https://…")
        row.addWidget(self.link_edit, 1)
        self.btn_download = QPushButton("Tải về")
        self.btn_download.clicked.connect(self.download_link)
        row.addWidget(self.btn_download)
        lay.addLayout(row)
        dl_row = QHBoxLayout()
        self.dl_bar = QProgressBar()
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        dl_row.addWidget(self.dl_bar, 1)
        self.dl_speed = QLabel("")
        dl_row.addWidget(self.dl_speed)
        lay.addLayout(dl_row)
        self.link_info = self._info_group()
        lay.addWidget(self.link_info["box"])
        lay.addStretch(1)
        self.tabs.addTab(tab, "Link")

    def _info_group(self) -> dict:
        """Cụm hiện info video dùng chung cho 2 tab."""
        box = QGroupBox("Thông tin video")
        form = QFormLayout(box)
        name = QLabel("—")
        name.setWordWrap(True)
        dur = QLabel("—")
        res = QLabel("—")
        form.addRow("Tên file:", name)
        form.addRow("Thời lượng:", dur)
        form.addRow("Phân giải:", res)
        track_row_widget = QWidget()
        track_row_lay = QHBoxLayout(track_row_widget)
        track_row_lay.setContentsMargins(0, 0, 0, 0)
        track_label = QLabel("Track audio:")
        track = QComboBox()
        track_row_lay.addWidget(track_label)
        track_row_lay.addWidget(track, 1)
        form.addRow(track_row_widget)
        box.setVisible(False)
        return {"box": box, "name": name, "dur": dur, "res": res,
                "track": track, "track_row": track_row_widget}

    def _show_info(self, info: dict, path: str) -> None:
        from media import extract as mextract
        try:
            streams = mextract.audio_streams(path)
        except Exception as e:  # noqa: BLE001
            error_box(self, "Không đọc được video",
                      f"Không đọc được file video:\n{e}\n\n"
                      "Cách khắc phục: thử file khác, hoặc kiểm tra FFmpeg "
                      "trong Cài đặt.")
            return
        info["name"].setText(Path(path).name)
        try:
            info["dur"].setText(fmt_time(mextract.duration_sec(path)))
        except Exception:  # noqa: BLE001
            info["dur"].setText("—")
        info["res"].setText(self._resolution(path))
        combo: QComboBox = info["track"]
        combo.clear()
        for i, st in enumerate(streams):
            lang = st.get("tags", {}).get("language", "")
            ch = st.get("channels", "?")
            codec = st.get("codec_name", "")
            label = f"Track {i + 1} — {codec}, {ch} kênh" \
                + (f" ({lang})" if lang else "")
            combo.addItem(label, i)
        info["track_row"].setVisible(len(streams) > 1)
        combo.setCurrentIndex(0)
        info["box"].setVisible(True)
        self.btn_start.setEnabled(True)

    @staticmethod
    def _resolution(path: str) -> str:
        from media import extract as mextract
        try:
            for st in mextract.probe(path).get("streams", []):
                if st.get("codec_type") == "video":
                    w, h = st.get("width"), st.get("height")
                    if w and h:
                        return f"{w}×{h}"
        except Exception:  # noqa: BLE001
            pass
        return "—"

    # -------------------------------------------------------------- tab File
    def pick_video_file(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Chọn video", "", VIDEO_FILTER)
        if not path or not Path(path).is_file():
            return
        self.video_path = path
        self.video_url = ""
        self._show_info(self.file_info, path)

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
        thread.finished.connect(lambda: setattr(self, "_dl_worker", None))
        # GIỮ reference: không giữ -> Python GC worker -> run() không chạy
        self._dl_worker = worker
        self._dl_thread = thread
        thread.start()

    def _on_dl_progress(self, pct: float, speed: str) -> None:
        self.dl_bar.setValue(int(pct))
        self.dl_speed.setText(f"{pct:.0f}% {speed}".strip())

    def _on_dl_finished(self, path: str) -> None:
        self.btn_download.setEnabled(True)
        self.dl_speed.setText("Tải xong")
        self.video_url = self.link_edit.text().strip()
        self.video_path = path
        self._show_info(self.link_info, path)
        info_box(self, "Tải xong",
                 f"Đã tải video về:\n{Path(path).name}\n\n"
                 "Giờ bạn có thể bấm [Bắt đầu lồng tiếng].")

    def _on_dl_failed(self, message: str) -> None:
        self.btn_download.setEnabled(True)
        self.dl_bar.setValue(0)
        self.dl_speed.setText("Tải lỗi")
        error_box(self, "Tải video thất bại", message)

    # --------------------------------------------------------------- tùy chọn
    def _build_options_group(self) -> QGroupBox:
        box = QGroupBox("Tùy chọn lồng tiếng")
        lay = QVBoxLayout(box)

        # giọng nam / nữ + nghe thử
        vg = QFormLayout()
        self.voice_male = QComboBox()
        self.voice_male.setEditable(True)
        self.voice_female = QComboBox()
        self.voice_female.setEditable(True)
        for cb, default in ((self.voice_male, self.settings.get("voice_male")),
                            (self.voice_female, self.settings.get("voice_female"))):
            cb.addItem(default)
            cb.setCurrentText(default)
        row_m = QHBoxLayout()
        row_m.addWidget(self.voice_male, 1)
        btn_pm = QPushButton("Nghe thử")
        btn_pm.clicked.connect(lambda: self.preview_voice(
            self.voice_male.currentText().strip(), "male", btn_pm))
        row_m.addWidget(btn_pm)
        row_f = QHBoxLayout()
        row_f.addWidget(self.voice_female, 1)
        btn_pf = QPushButton("Nghe thử")
        btn_pf.clicked.connect(lambda: self.preview_voice(
            self.voice_female.currentText().strip(), "female", btn_pf))
        row_f.addWidget(btn_pf)
        vg.addRow("Giọng nam:", row_m)
        vg.addRow("Giọng nữ:", row_f)
        lay.addLayout(vg)

        self.provider = QComboBox()
        self.provider.addItem("9Router (mặc định)", "9router")
        self.provider.addItem("Ollama (chạy local)", "ollama")
        cur = self.settings.get("translate_provider", "9router")
        self.provider.setCurrentIndex(0 if cur == "9router" else 1)
        pf = QFormLayout()
        pf.addRow("Nguồn dịch:", self.provider)
        lay.addLayout(pf)

        self.chk_review = QCheckBox("Dừng để duyệt sau mỗi chặng "
                                    "(sửa sub gốc, sửa bản dịch)")
        self.chk_review.setChecked(bool(self.settings.get("review_stops", True)))
        self.chk_overnight = QCheckBox("Chế độ qua đêm (chạy liền 9 bước, "
                                       "không dừng chờ người)")
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
        btn.setEnabled(False)
        btn.setText("Đang tạo…")
        # Thư mục tạm riêng cho giọng mẫu: không tạo thư mục job mồ côi
        # (jobs/<id>/) trên đĩa khi user chỉ bấm [Nghe thử] mà chưa bao giờ
        # bắt đầu job thật. Giữ reference tới khi đóng app.
        tmp = tempfile.TemporaryDirectory(prefix="vietdub_nghe_thu_")
        self._pv_tmps.append(tmp)
        tmpdir = Path(tmp.name)
        worker = VoicePreviewWorker(voice, gender, tmpdir)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.done.connect(
            lambda wav: self._on_preview_done(wav, btn))
        worker.failed.connect(
            lambda msg: self._on_preview_failed(msg, btn))
        thread.started.connect(worker.run)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        # done/failed phát trong worker thread khi loop còn sống ->
        # deleteLater được xử lý ngay, không leak worker mỗi lần nghe thử.
        worker.done.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_pv_worker", None))
        # GIỮ reference: không giữ -> Python GC worker -> run() không chạy
        self._pv_worker = worker
        self._pv_thread = thread
        thread.start()

    def _on_preview_done(self, wav: str, btn: QPushButton) -> None:
        btn.setEnabled(True)
        btn.setText("Nghe thử")
        self._player.setSource(QUrl.fromLocalFile(wav))
        self._player.play()

    def _on_preview_failed(self, message: str, btn: QPushButton) -> None:
        btn.setEnabled(True)
        btn.setText("Nghe thử")
        error_box(self, "Không nghe thử được",
                  f"{message}\n\nCách khắc phục: kiểm tra mạng (Edge-TTS cần "
                  "kết nối tới Microsoft), rồi bấm Nghe thử lại.")

    # ------------------------------------------------------------------ bắt đầu
    def open_settings(self) -> None:
        from ui.common import open_settings_dialog
        if open_settings_dialog(self, self.settings):
            # settings đã được lưu trong dialog; áp lại vào UI chính
            self.voice_male.setCurrentText(self.settings.get("voice_male"))
            self.voice_female.setCurrentText(self.settings.get("voice_female"))
            cur = self.settings.get("translate_provider", "9router")
            self.provider.setCurrentIndex(0 if cur == "9router" else 1)
            self.chk_review.setChecked(bool(self.settings.get("review_stops", True)))
            self.chk_overnight.setChecked(bool(self.settings.get("overnight", False)))

    def closeEvent(self, e) -> None:  # noqa: N802
        # Dọn thư mục tạm của [Nghe thử] khi đóng app.
        for tmp in self._pv_tmps:
            try:
                tmp.cleanup()
            except Exception:  # noqa: BLE001
                pass
        self._pv_tmps.clear()
        super().closeEvent(e)

    def _audio_track_index(self) -> int:
        info = self.file_info if self.tabs.currentIndex() == 0 else self.link_info
        if info["track_row"].isVisible():
            return int(info["track"].currentData() or 0)
        return 0

    def start_job(self) -> None:
        if not self.video_path or not Path(self.video_path).is_file():
            error_box(self, "Chưa có video",
                      "Hãy chọn file video (tab File) hoặc tải video từ link "
                      "(tab Link) trước khi bắt đầu.")
            return
        provider = self.provider.currentData()
        if provider == "9router" and not self.settings.get("nine_router_key"):
            if not confirm_box(
                    self, "Chưa nhập API key 9Router",
                    "Bạn chưa nhập API key 9Router trong Cài đặt.\n"
                    "Vẫn bắt đầu? (bước dịch có thể lỗi, hoặc tự chuyển "
                    "sang Ollama nếu đã cấu hình)"):
                return
        if provider == "ollama" and not self.settings.get("ollama_model"):
            error_box(self, "Chưa cấu hình Ollama",
                      "Bạn chọn nguồn dịch Ollama nhưng chưa nhập tên model "
                      "trong Cài đặt.\n\nCách khắc phục: mở Cài đặt → tab Dịch "
                      "thuật → nhập tên model (vd llama3.1) rồi bấm Lưu.")
            return

        job = self._ensure_job()
        proj = job.project
        proj.name = Path(self.video_path).stem
        if self.video_url:
            proj.video_source = "url"
            proj.video_url = self.video_url
            proj.video_in = self.video_path  # file đã tải (fetch sẽ dùng lại)
        else:
            proj.video_source = "file"
            proj.video_in = self.video_path
        out_dir = self.out_dir.text().strip()
        if out_dir:
            out_name = Path(self.video_path).stem + "_vidub.mp4"
            proj.video_out = str(Path(out_dir) / out_name)
        else:
            proj.video_out = ""
        proj.voice_male = self.voice_male.currentText().strip() \
            or self.settings.get("voice_male")
        proj.voice_female = self.voice_female.currentText().strip() \
            or self.settings.get("voice_female")
        proj.translate_provider = provider
        proj.review_stops = self.chk_review.isChecked()
        proj.overnight = self.chk_overnight.isChecked()
        proj.audio_track = self._audio_track_index()
        proj.proper_nouns = list(self.settings.get("proper_nouns", []))

        # lưu lựa chọn nhanh vào settings để mở lại app vẫn giữ
        self.settings.set("voice_male", proj.voice_male)
        self.settings.set("voice_female", proj.voice_female)
        self.settings.set("translate_provider", provider)
        self.settings.set("review_stops", proj.review_stops)
        self.settings.set("overnight", proj.overnight)
        self.settings.save()

        from project import io as pio
        pio.save_project(job.job_dir, proj)

        from ui.progress import ProgressWindow
        self._progress_win = ProgressWindow(job, self.settings,
                                            on_close=self._back_to_main)
        self._progress_win.show()
        self.hide()
        self._progress_win.begin()

    def _back_to_main(self) -> None:
        self.job = None
        self.video_path = ""
        self.video_url = ""
        self.btn_start.setEnabled(False)
        self.file_info["box"].setVisible(False)
        self.link_info["box"].setVisible(False)
        self.dl_bar.setValue(0)
        self.dl_speed.setText("")
        self.show()
