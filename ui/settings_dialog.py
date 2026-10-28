# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Dialog Cài đặt (mở được từ mọi màn hình).

Mọi giá trị lưu thật vào settings JSON (%APPDATA%/VietDub/settings.json
trên Windows, ~/.config/VietDub/settings.json trên Linux/macOS) — mở lại
app vẫn giữ nguyên lựa chọn cũ.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from core.settings import DEFAULTS, Settings
from ui.common import error_box
from ui.theme import APP_BACKGROUND, UI_COLORS


class OllamaCheckWorker(QObject):
    finished = Signal(bool, str)
    completed = Signal()

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    @Slot()
    def run(self) -> None:
        try:
            import requests
            response = requests.get(f"{self.url}/api/tags", timeout=8)
            response.raise_for_status()
            models = [str(model.get("name", "?"))
                      for model in response.json().get("models", [])]
            hint = ("Các mô hình đã tải: " + ", ".join(models)
                    if models else "Chưa có mô hình. Chạy ollama pull <tên-mô-hình>.")
            self.finished.emit(True, f"Đã kết nối Ollama. {hint} "
                               "Nhập tên mô hình bên trên rồi bấm Lưu.")
        except Exception:  # noqa: BLE001 - hiển thị hướng dẫn, không phơi lỗi thư viện
            self.finished.emit(False, f"Không kết nối được Ollama tại {self.url}. "
                               "Mở Ollama (ollama serve), kiểm tra địa chỉ máy chủ "
                               "và mô hình đã tải, rồi bấm Kiểm tra lại.")
        finally:
            self.completed.emit()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._check_thread: QThread | None = None
        self._check_worker: OllamaCheckWorker | None = None
        self._pending_result: int | None = None
        self.setObjectName("settingsRoot")
        self.setStyleSheet(f"QWidget#settingsRoot, QWidget#settingsPage {{ background: {APP_BACKGROUND}; }}")
        self.setWindowTitle("Cài đặt VietDub")
        self.resize(820, 760)
        self.setMinimumSize(620, 480)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title = QLabel("Cài đặt VietDub")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs, 1)
        self._build_translate_tab()
        self._build_asr_tab()
        self._build_voice_tab()
        self._build_video_tab()
        self._build_names_tab()

        row = QHBoxLayout()
        btn_default = QPushButton("Khôi phục mặc định")
        btn_default.clicked.connect(self.restore_defaults)
        row.addWidget(btn_default)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Lưu")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Hủy")
        self.buttons.button(QDialogButtonBox.Save).setProperty("role", "primary")
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        root.addLayout(row)

    def _add_scroll_tab(self, tab: QWidget, label: str) -> None:
        tab.setObjectName("settingsPage")
        form = tab.layout()
        if isinstance(form, QFormLayout):
            form.setRowWrapPolicy(QFormLayout.WrapLongRows)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for combo in tab.findChildren(QComboBox):
            combo.setMinimumContentsLength(12)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, label)

    # ------------------------------------------------------------- tab dịch
    def _build_translate_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        f.setContentsMargins(16, 16, 16, 16)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        self.oa_key = QLineEdit()
        self.oa_key.setEchoMode(QLineEdit.Password)
        self.oa_key.setText(self.settings.get("openai_api_key", ""))
        f.addRow("Khóa API OpenAI:", self.oa_key)
        self.oa_model = QLineEdit()
        self.oa_model.setText(self.settings.get("openai_model", "gpt-4.1"))
        f.addRow("Mô hình OpenAI:", self.oa_model)
        self.oa_url = QLineEdit()
        self.oa_url.setText(self.settings.get(
            "openai_url", "https://api.openai.com/v1"))
        f.addRow("Máy chủ OpenAI:", self.oa_url)
        self.nr_key = QLineEdit()
        self.nr_key.setEchoMode(QLineEdit.Password)
        self.nr_key.setText(self.settings.get("nine_router_key", ""))
        f.addRow("Khóa API 9Router:", self.nr_key)
        self.nr_model = QLineEdit()
        self.nr_model.setText(self.settings.get("nine_router_model", ""))
        f.addRow("Mô hình 9Router:", self.nr_model)
        self.nr_url = QLineEdit()
        self.nr_url.setText(self.settings.get("nine_router_url", ""))
        f.addRow("Máy chủ 9Router:", self.nr_url)
        self.ol_url = QLineEdit()
        self.ol_url.setText(self.settings.get("ollama_url", ""))
        f.addRow("Máy chủ Ollama:", self.ol_url)
        row = QHBoxLayout()
        self.ol_model = QLineEdit()
        self.ol_model.setText(self.settings.get("ollama_model", ""))
        self.ol_model.setPlaceholderText("vd llama3.1, qwen2.5…")
        row.addWidget(self.ol_model, 1)
        self.btn_check = QPushButton("Kiểm tra kết nối")
        self.btn_check.clicked.connect(self.check_ollama)
        row.addWidget(self.btn_check)
        f.addRow("Mô hình Ollama:", row)
        self.ollama_status = QLabel("Kiểm tra kết nối sau khi mở Ollama trên máy của bạn.")
        self.ollama_status.setWordWrap(True)
        self.ollama_status.setTextFormat(Qt.PlainText)
        self.ollama_status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.ollama_status.setProperty("role", "secondary")
        f.addRow(self.ollama_status)
        self.ol_url.textChanged.connect(self._on_ollama_url_changed)
        self.llm_temp = QDoubleSpinBox()
        self.llm_temp.setRange(0.0, 1.0)
        self.llm_temp.setSingleStep(0.05)
        self.llm_temp.setValue(float(self.settings.get("llm_temperature", 0.2)))
        f.addRow("Độ sáng tạo bản dịch:", self.llm_temp)
        self.tr_batch = QSpinBox()
        self.tr_batch.setRange(1, 100)
        self.tr_batch.setValue(int(self.settings.get("translate_batch", 20)))
        f.addRow("Số câu mỗi lượt dịch:", self.tr_batch)
        note = QLabel("OpenAI API tính phí riêng, không dùng chung gói ChatGPT. "
                      "Có thể chọn 9Router hoặc Ollama nếu không có API key.")
        note.setWordWrap(True)
        note.setProperty("role", "secondary")
        f.addRow(note)
        self._add_scroll_tab(tab, "Dịch thuật")

    @Slot(str)
    def _on_ollama_url_changed(self, _text: str) -> None:
        if self._pending_result is not None:
            return
        message = "Địa chỉ Ollama đã thay đổi. Hãy kiểm tra kết nối với địa chỉ mới."
        if self._check_thread is not None:
            if self.ol_url.text().strip().rstrip("/") == self._check_url:
                message = "Đang kết nối Ollama… Bạn vẫn có thể sửa các cài đặt khác."
            else:
                message = ("Đang hoàn tất kiểm tra địa chỉ trước. "
                           "Hãy kiểm tra lại địa chỉ mới sau khi tác vụ kết thúc.")
        self.ollama_status.setText(message)
        self.ollama_status.setStyleSheet(f"color: {UI_COLORS['secondary_text']};")
        QTimer.singleShot(30, self._reveal_ollama_status)

    def check_ollama(self) -> None:
        if self._check_thread is not None:
            return
        url = self.ol_url.text().strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            self._check_feedback("Nhập địa chỉ Ollama bắt đầu bằng http:// hoặc https://, "
                                 "ví dụ http://localhost:11434, rồi kiểm tra lại.", False)
            self.ol_url.setFocus()
            return
        self._check_url = url
        self.btn_check.setEnabled(False)
        self.btn_check.setText("Đang kiểm tra…")
        self.ollama_status.setText("Đang kết nối Ollama… Bạn vẫn có thể sửa các cài đặt khác.")
        self.ollama_status.setStyleSheet(f"color: {UI_COLORS['secondary_text']};")
        worker = OllamaCheckWorker(url)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ollama_result)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(self._on_check_stopped)
        self._check_worker, self._check_thread = worker, thread
        thread.start()

    def _check_feedback(self, text: str, success: bool) -> None:
        self.ollama_status.setText(text)
        color = UI_COLORS["success" if success else "danger"]
        self.ollama_status.setStyleSheet(f"color: {color};")
        QTimer.singleShot(30, self._reveal_ollama_status)

    @Slot()
    def _reveal_ollama_status(self) -> None:
        self.tabs.widget(0).ensureWidgetVisible(self.ollama_status, 0, 12)

    @Slot(bool, str)
    def _on_ollama_result(self, success: bool, message: str) -> None:
        if self._pending_result is not None:
            return
        if self.ol_url.text().strip().rstrip("/") != self._check_url:
            self._check_feedback("Địa chỉ Ollama đã thay đổi. Bấm Kiểm tra lại để kiểm tra địa chỉ mới.",
                                 False)
            return
        self._check_feedback(message, success)

    @Slot()
    def _on_check_stopped(self) -> None:
        thread = self._check_thread
        self._check_worker = self._check_thread = None
        thread.deleteLater()
        self.btn_check.setEnabled(True)
        self.btn_check.setText("Kiểm tra lại")
        if self._pending_result is not None:
            self.setEnabled(True)
            self.done(self._pending_result)

    def done(self, result: int) -> None:
        # Keep both QObjects alive until the bounded network operation exits.
        # Save, Cancel, Escape and the window close button all use this path.
        if self._check_thread is not None:
            if self._pending_result is None:
                self._pending_result = result
            self.setEnabled(False)
            self.ollama_status.setText("Đang hoàn tất kiểm tra kết nối trước khi đóng…")
            return
        super().done(result)

    def accept(self) -> None:
        self.done(QDialog.Accepted)

    def reject(self) -> None:
        self.done(QDialog.Rejected)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._check_thread is not None:
            self.done(QDialog.Rejected)
            event.ignore()
            return
        super().closeEvent(event)

    # -------------------------------------------------------------- tab ASR
    def _build_asr_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        f.setContentsMargins(16, 16, 16, 16)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        self.asr_backend = QComboBox()
        self.asr_backend.addItem("Whisper + CAM++ tách loa", "whisper")
        self.asr_backend.addItem("FunASR trực tiếp", "funasr")
        self.asr_backend.addItem(
            "Qwen 1.7B + timestamp + CAM++ (chậm)", "qwen")
        backend = self.settings.get("asr_backend", "whisper")
        idx = self.asr_backend.findData(backend)
        self.asr_backend.setCurrentIndex(max(0, idx))
        f.addRow("Bộ nhận dạng lời nói:", self.asr_backend)
        self.whisper_model = QLineEdit(
            self.settings.get("whisper_model", "large-v3-turbo"))
        f.addRow("Mô hình Whisper:", self.whisper_model)
        self.asr_model = QComboBox()
        self.asr_model.setEditable(True)
        self.asr_model.addItem(str(self.settings.get("asr_model")))
        self.asr_model.setCurrentText(str(self.settings.get("asr_model")))
        f.addRow("Mô hình FunASR:", self.asr_model)
        self.vad_model = QLineEdit(self.settings.get("vad_model", ""))
        f.addRow("Mô hình phát hiện giọng:", self.vad_model)
        self.punc_model = QLineEdit(self.settings.get("punc_model", ""))
        f.addRow("Mô hình dấu câu:", self.punc_model)
        self.spk_model = QLineEdit(self.settings.get("spk_model", ""))
        f.addRow("Mô hình tách người nói:", self.spk_model)
        self.asr_conf = QDoubleSpinBox()
        self.asr_conf.setRange(0.0, 1.0)
        self.asr_conf.setSingleStep(0.05)
        self.asr_conf.setValue(float(self.settings.get("asr_confidence_low", 0.5)))
        f.addRow("Ngưỡng độ tin cậy thấp:", self.asr_conf)
        confidence_note = QLabel(
            "Câu nào ASR nghe dưới ngưỡng này sẽ được đánh dấu "
            "để bạn kiểm tra kỹ ở màn duyệt.")
        confidence_note.setWordWrap(True)
        confidence_note.setProperty("role", "secondary")
        f.addRow(confidence_note)
        qwen_note = QLabel(
            "Qwen dùng ForcedAligner để tạo timestamp và CAM++ để gán loa. "
            "Model chạy lần lượt để giảm RAM; lần đầu cần tải khoảng 6 GB "
            "và xử lý chậm hơn Whisper nhiều; khuyến nghị máy có ít nhất "
            "16 GB RAM.")
        qwen_note.setWordWrap(True)
        qwen_note.setProperty("role", "secondary")
        f.addRow(qwen_note)
        self._add_scroll_tab(tab, "Nhận dạng")

    # ------------------------------------------------------------ tab giọng
    def _build_voice_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        f.setContentsMargins(16, 16, 16, 16)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        self.pitch_male = QDoubleSpinBox()
        self.pitch_male.setRange(50, 400)
        self.pitch_male.setValue(float(self.settings.get("pitch_male_max_hz", 160)))
        f.addRow("Cao độ tối đa giọng nam (Hz):", self.pitch_male)
        self.pitch_female = QDoubleSpinBox()
        self.pitch_female.setRange(50, 400)
        self.pitch_female.setValue(
            float(self.settings.get("pitch_female_min_hz", 165)))
        f.addRow("Cao độ tối thiểu giọng nữ (Hz):", self.pitch_female)
        self.dub_vol = QSpinBox()
        self.dub_vol.setRange(0, 150)
        self.dub_vol.setSuffix(" %")
        self.dub_vol.setValue(int(float(self.settings.get("dub_volume", 1.0)) * 100))
        f.addRow("Âm lượng tiếng lồng:", self.dub_vol)
        self.orig_vol = QSpinBox()
        self.orig_vol.setRange(0, 100)
        self.orig_vol.setSuffix(" %")
        self.orig_vol.setValue(
            int(float(self.settings.get("orig_volume", 0.15)) * 100))
        f.addRow("Âm lượng tiếng gốc:", self.orig_vol)
        self.tts_rate = QLineEdit(self.settings.get("tts_rate", "+0%"))
        self.tts_rate.setPlaceholderText("+0%")
        f.addRow("Tốc độ đọc TTS:", self.tts_rate)
        self.tts_pitch = QLineEdit(self.settings.get("tts_pitch", "+0Hz"))
        self.tts_pitch.setPlaceholderText("+0Hz")
        f.addRow("Cao độ giọng TTS:", self.tts_pitch)
        self.tts_conc = QSpinBox()
        self.tts_conc.setRange(1, 20)
        self.tts_conc.setValue(int(self.settings.get("tts_concurrency", 10)))
        f.addRow("Số câu TTS song song:", self.tts_conc)
        self._add_scroll_tab(tab, "Giọng nói")

    # ------------------------------------------------------------ tab video
    def _build_video_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        f.setContentsMargins(16, 16, 16, 16)
        f.setHorizontalSpacing(16)
        f.setVerticalSpacing(11)
        self.sub_mode = QComboBox()
        self.sub_mode.addItem("Gắn cứng vào video", "burn")
        self.sub_mode.addItem("Xuất file .srt rời", "srt")
        self.sub_mode.addItem("Không thêm phụ đề vào video", "none")
        cur = self.settings.get("sub_mode", "burn")
        self.sub_mode.setCurrentIndex(max(0, self.sub_mode.findData(cur)))
        f.addRow("Chế độ phụ đề:", self.sub_mode)
        row_font = QHBoxLayout()
        self.sub_font = QLineEdit(self.settings.get("sub_font", "") or "")
        self.sub_font.setPlaceholderText("Để trống = font mặc định của FFmpeg")
        row_font.addWidget(self.sub_font, 1)
        btn_font = QPushButton("Chọn…")
        btn_font.clicked.connect(self.browse_font)
        row_font.addWidget(btn_font)
        f.addRow("Font phụ đề:", row_font)
        self.sub_font_size = QSpinBox()
        self.sub_font_size.setRange(0, 200)
        self.sub_font_size.setSpecialValueText("Tự động")
        self.sub_font_size.setValue(int(self.settings.get("sub_font_size", 0) or 0))
        f.addRow("Cỡ chữ phụ đề:", self.sub_font_size)
        self.sub_font_color = QLineEdit(self.settings.get("sub_font_color", "") or "")
        self.sub_font_color.setPlaceholderText("vd FFFF00 (vàng) — để trống = mặc định")
        f.addRow("Màu chữ phụ đề:", self.sub_font_color)
        self.crf = QSpinBox()
        self.crf.setRange(18, 28)
        self.crf.setValue(int(self.settings.get("crf", 20)))
        f.addRow("Chất lượng video (CRF):", self.crf)
        self.visual_cleanup_enabled = QCheckBox("Xử lý chữ/logo gốc (OCR đề xuất hoặc tự chọn vùng)")
        self.visual_cleanup_enabled.setChecked(bool(self.settings.get("visual_cleanup_enabled", False)))
        f.addRow(self.visual_cleanup_enabled)
        self.visual_cleanup_backend = QComboBox()
        self.visual_cleanup_backend.addItem("OpenCV / clean-plate (nhẹ)", "cv")
        self.visual_cleanup_backend.addItem("AI video inpainting (cần cài VSR riêng)", "vsr")
        self.visual_cleanup_backend.addItem("LaMa CPU trực tiếp (model pretrained)", "lama-cpu")
        self.visual_cleanup_backend.addItem("Kết hợp clean-plate và LaMa (plan đã duyệt)", "hybrid")
        self.visual_cleanup_backend.setCurrentIndex(max(0,
            self.visual_cleanup_backend.findData(self.settings.get("visual_cleanup_backend","cv"))))
        f.addRow("Engine xử lý:", self.visual_cleanup_backend)
        self.visual_vsr_mode = QComboBox()
        self.visual_vsr_mode.addItem("STTN + OCR (tự phát hiện text)", "sttn-det")
        self.visual_vsr_mode.addItem("STTN vùng chọn", "sttn-auto")
        self.visual_vsr_mode.addItem("LaMa", "lama")
        self.visual_vsr_mode.addItem("ProPainter", "propainter")
        self.visual_vsr_mode.setCurrentIndex(max(0,
            self.visual_vsr_mode.findData(self.settings.get("visual_vsr_mode","sttn-det"))))
        f.addRow("Model AI (VSR):", self.visual_vsr_mode)
        vsr_row = QHBoxLayout()
        self.visual_vsr_root = QLineEdit(self.settings.get("visual_vsr_root","") or "")
        self.visual_vsr_root.setPlaceholderText("Thư mục VSR có backend/main.py")
        vsr_row.addWidget(self.visual_vsr_root, 1)
        browse_vsr = QPushButton("Chọn…")
        browse_vsr.clicked.connect(self.browse_visual_vsr)
        vsr_row.addWidget(browse_vsr)
        f.addRow("VSR local:", vsr_row)
        model_row = QHBoxLayout()
        self.visual_lama_weight = QLineEdit(self.settings.get("visual_lama_weight_path","") or "")
        self.visual_lama_weight.setPlaceholderText("Đường dẫn big-lama.pt")
        model_row.addWidget(self.visual_lama_weight, 1)
        browse_model = QPushButton("Chọn…")
        browse_model.clicked.connect(self.browse_visual_lama)
        model_row.addWidget(browse_model)
        f.addRow("LaMa CPU checkpoint:", model_row)
        self.visual_cleanup_auto_logo = QCheckBox("Thử nhận diện logo cố định (nguy cơ nhầm vùng; cần kiểm duyệt)")
        self.visual_cleanup_auto_logo.setChecked(bool(self.settings.get("visual_cleanup_auto_logo", False)))
        f.addRow(self.visual_cleanup_auto_logo)
        self.visual_cleanup_mode = QComboBox()
        self.visual_cleanup_mode.addItem("Làm mờ Gaussian (nhanh)", "blur")
        self.visual_cleanup_mode.addItem("Inpaint Telea (xóa và lấp nền)", "inpaint")
        self.visual_cleanup_mode.setCurrentIndex(max(0, self.visual_cleanup_mode.findData(
            self.settings.get("visual_cleanup_mode", "blur"))))
        f.addRow("Xử lý chữ/logo:", self.visual_cleanup_mode)
        self.visual_cleanup_interval = QDoubleSpinBox()
        self.visual_cleanup_interval.setRange(0.15, 3.0)
        self.visual_cleanup_interval.setDecimals(2)
        self.visual_cleanup_interval.setSingleStep(0.1)
        self.visual_cleanup_interval.setSuffix(" giây")
        self.visual_cleanup_interval.setValue(float(self.settings.get("visual_cleanup_interval_sec", 0.65)))
        f.addRow("Lấy mẫu OCR mỗi:", self.visual_cleanup_interval)
        manual_row = QHBoxLayout()
        self.visual_cleanup_review_plan = QLineEdit(
            self.settings.get("visual_cleanup_review_plan", "") or "")
        self.visual_cleanup_review_plan.setPlaceholderText(
            "Plan vùng chọn từ khung hình (hoặc JSON đã duyệt)")
        manual_row.addWidget(self.visual_cleanup_review_plan, 1)
        browse_review = QPushButton("Chọn…")
        browse_review.clicked.connect(self.browse_visual_plan)
        manual_row.addWidget(browse_review)
        f.addRow("Plan vùng xử lý:", manual_row)
        note_visual = QLabel(
            "Chọn video → 'Chọn vùng chữ/logo cần làm mờ…' để kéo khoanh và xem trước "
            "Blur/Mosaic/Inpaint. Chế độ tự chọn KHÔNG cần PaddleOCR; nút gợi ý OCR "
            "mới cần model. Plan gắn với đúng video nguồn, đổi nguồn cần chọn lại. "
            "Chú ý: chọn vùng rộng có thể làm mờ cả người/vật thể bên dưới.")
        note_visual.setWordWrap(True)
        f.addRow(note_visual)
        f.addRow(QLabel("CRF càng nhỏ video càng nét (file càng nặng)."))
        row = QHBoxLayout()
        self.ffmpeg_path = QLineEdit(self.settings.get("ffmpeg_path", "ffmpeg"))
        row.addWidget(self.ffmpeg_path, 1)
        btn_browse = QPushButton("Chọn…")
        btn_browse.clicked.connect(self.browse_ffmpeg)
        row.addWidget(btn_browse)
        f.addRow("Đường dẫn FFmpeg:", row)
        self._add_scroll_tab(tab, "Video / phụ đề")

    def browse_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn font phụ đề",
            "", "Font (*.ttf *.otf *.ttc);;Tất cả (*.*)")
        if path:
            self.sub_font.setText(path)

    def browse_visual_lama(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn checkpoint LaMa", "", "TorchScript (*.pt);;Tất cả (*.*)")
        if path:
            self.visual_lama_weight.setText(path)

    def browse_visual_vsr(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục VSR")
        if path:
            self.visual_vsr_root.setText(path)

    def browse_visual_plan(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn plan clean-plate đã duyệt",
            "", "JSON (*.json);;Tất cả (*.*)")
        if path:
            self.visual_cleanup_review_plan.setText(path)

    def browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ffmpeg")
        if path:
            self.ffmpeg_path.setText(path)

    # --------------------------------------------------------- tab tên riêng
    def _build_names_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)
        note = QLabel(
            "Danh sách tên riêng (mỗi dòng một tên) — prompt dịch sẽ giữ "
            "nguyên/phiên âm Hán-Việt các tên này, không dịch nghĩa:")
        note.setWordWrap(True)
        note.setProperty("role", "secondary")
        lay.addWidget(note)
        self.names_edit = QPlainTextEdit()
        self.names_edit.setPlainText(
            "\n".join(self.settings.get("proper_nouns", [])))
        lay.addWidget(self.names_edit)
        self._add_scroll_tab(tab, "Tên riêng")

    # ------------------------------------------------------------------ lưu
    def restore_defaults(self) -> None:
        self.oa_key.setText(str(DEFAULTS["openai_api_key"]))
        self.oa_model.setText(str(DEFAULTS["openai_model"]))
        self.oa_url.setText(str(DEFAULTS["openai_url"]))
        self.nr_key.setText(str(DEFAULTS["nine_router_key"]))
        self.nr_model.setText(str(DEFAULTS["nine_router_model"]))
        self.nr_url.setText(str(DEFAULTS["nine_router_url"]))
        self.ol_url.setText(str(DEFAULTS["ollama_url"]))
        self.ol_model.setText(str(DEFAULTS["ollama_model"]))
        self.llm_temp.setValue(float(DEFAULTS["llm_temperature"]))
        self.tr_batch.setValue(int(DEFAULTS["translate_batch"]))
        self.asr_backend.setCurrentIndex(
            max(0, self.asr_backend.findData(DEFAULTS["asr_backend"])))
        self.whisper_model.setText(str(DEFAULTS["whisper_model"]))
        self.asr_model.setCurrentText(str(DEFAULTS["asr_model"]))
        self.vad_model.setText(str(DEFAULTS["vad_model"]))
        self.punc_model.setText(str(DEFAULTS["punc_model"]))
        self.spk_model.setText(str(DEFAULTS["spk_model"]))
        self.asr_conf.setValue(float(DEFAULTS["asr_confidence_low"]))
        self.pitch_male.setValue(float(DEFAULTS["pitch_male_max_hz"]))
        self.pitch_female.setValue(float(DEFAULTS["pitch_female_min_hz"]))
        self.dub_vol.setValue(int(float(DEFAULTS["dub_volume"]) * 100))
        self.orig_vol.setValue(int(float(DEFAULTS["orig_volume"]) * 100))
        self.tts_rate.setText(str(DEFAULTS["tts_rate"]))
        self.tts_pitch.setText(str(DEFAULTS["tts_pitch"]))
        self.tts_conc.setValue(int(DEFAULTS["tts_concurrency"]))
        self.sub_mode.setCurrentIndex(max(0, self.sub_mode.findData(DEFAULTS["sub_mode"])))
        self.visual_cleanup_enabled.setChecked(bool(DEFAULTS["visual_cleanup_enabled"]))
        self.visual_cleanup_backend.setCurrentIndex(max(0,
            self.visual_cleanup_backend.findData(DEFAULTS["visual_cleanup_backend"])))
        self.visual_vsr_mode.setCurrentIndex(max(0,
            self.visual_vsr_mode.findData(DEFAULTS["visual_vsr_mode"])))
        self.visual_vsr_root.setText(str(DEFAULTS["visual_vsr_root"]))
        self.visual_lama_weight.setText(str(DEFAULTS["visual_lama_weight_path"]))
        self.visual_cleanup_auto_logo.setChecked(bool(DEFAULTS["visual_cleanup_auto_logo"]))
        self.visual_cleanup_mode.setCurrentIndex(max(0,
            self.visual_cleanup_mode.findData(DEFAULTS["visual_cleanup_mode"])))
        self.visual_cleanup_interval.setValue(float(DEFAULTS["visual_cleanup_interval_sec"]))
        self.visual_cleanup_review_plan.setText(str(DEFAULTS["visual_cleanup_review_plan"]))
        self.sub_font.setText(str(DEFAULTS["sub_font"]))
        self.sub_font_size.setValue(int(DEFAULTS["sub_font_size"]))
        self.sub_font_color.setText(str(DEFAULTS["sub_font_color"]))
        self.crf.setValue(int(DEFAULTS["crf"]))
        self.ffmpeg_path.setText(str(DEFAULTS["ffmpeg_path"]))
        self.names_edit.setPlainText("")

    def save(self) -> None:
        if self.pitch_male.value() >= self.pitch_female.value():
            error_box(self, "Ngưỡng cao độ không hợp lệ",
                      "Cao độ tối đa của nam phải nhỏ hơn cao độ tối thiểu "
                      "của nữ (giọng nam trầm hơn giọng nữ).")
            return
        names = [ln.strip() for ln in
                 self.names_edit.toPlainText().splitlines() if ln.strip()]
        self.settings.update({
            "openai_api_key": self.oa_key.text().strip(),
            "openai_model": self.oa_model.text().strip() or
            DEFAULTS["openai_model"],
            "openai_url": self.oa_url.text().strip() or
            DEFAULTS["openai_url"],
            "nine_router_key": self.nr_key.text().strip(),
            "nine_router_model": self.nr_model.text().strip(),
            "nine_router_url": self.nr_url.text().strip() or
            DEFAULTS["nine_router_url"],
            "ollama_url": self.ol_url.text().strip() or
            DEFAULTS["ollama_url"],
            "ollama_model": self.ol_model.text().strip(),
            "llm_temperature": self.llm_temp.value(),
            "translate_batch": self.tr_batch.value(),
            "asr_backend": self.asr_backend.currentData(),
            "whisper_model": self.whisper_model.text().strip() or
            DEFAULTS["whisper_model"],
            "asr_model": self.asr_model.currentText().strip(),
            "vad_model": self.vad_model.text().strip(),
            "punc_model": self.punc_model.text().strip(),
            "spk_model": self.spk_model.text().strip(),
            "asr_confidence_low": self.asr_conf.value(),
            "pitch_male_max_hz": self.pitch_male.value(),
            "pitch_female_min_hz": self.pitch_female.value(),
            "dub_volume": self.dub_vol.value() / 100.0,
            "orig_volume": self.orig_vol.value() / 100.0,
            "tts_rate": self.tts_rate.text().strip() or "+0%",
            "tts_pitch": self.tts_pitch.text().strip() or "+0Hz",
            "tts_concurrency": self.tts_conc.value(),
            "sub_mode": self.sub_mode.currentData(),
            "visual_cleanup_enabled": self.visual_cleanup_enabled.isChecked(),
            "visual_cleanup_backend": self.visual_cleanup_backend.currentData(),
            "visual_vsr_mode": self.visual_vsr_mode.currentData(),
            "visual_vsr_root": self.visual_vsr_root.text().strip(),
            "visual_lama_weight_path": self.visual_lama_weight.text().strip(),
            "visual_cleanup_auto_logo": self.visual_cleanup_auto_logo.isChecked(),
            "visual_cleanup_mode": self.visual_cleanup_mode.currentData(),
            "visual_cleanup_interval_sec": self.visual_cleanup_interval.value(),
            "visual_cleanup_review_plan": self.visual_cleanup_review_plan.text().strip(),
            "sub_font": self.sub_font.text().strip(),
            "sub_font_size": self.sub_font_size.value(),
            "sub_font_color": self.sub_font_color.text().strip().lstrip("#"),
            "crf": self.crf.value(),
            "ffmpeg_path": self.ffmpeg_path.text().strip() or "ffmpeg",
            "proper_nouns": names,
        })
        self.settings.save()
        self.accept()
