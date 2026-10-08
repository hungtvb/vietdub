# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Dialog Cài đặt (mở được từ mọi màn hình).

Mọi giá trị lưu thật vào settings JSON (%APPDATA%/VietDub/settings.json
trên Windows, ~/.config/VietDub/settings.json trên Linux/macOS) — mở lại
app vẫn giữ nguyên lựa chọn cũ.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from core.settings import DEFAULTS, Settings
from ui.common import error_box, info_box


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Cài đặt VietDub")
        self.resize(560, 520)
        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
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
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        row.addWidget(self.buttons)
        root.addLayout(row)

    # ------------------------------------------------------------- tab dịch
    def _build_translate_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        self.nr_key = QLineEdit()
        self.nr_key.setEchoMode(QLineEdit.Password)
        self.nr_key.setText(self.settings.get("nine_router_key", ""))
        f.addRow("API key 9Router:", self.nr_key)
        self.nr_model = QLineEdit()
        self.nr_model.setText(self.settings.get("nine_router_model", ""))
        f.addRow("Model 9Router:", self.nr_model)
        self.nr_url = QLineEdit()
        self.nr_url.setText(self.settings.get("nine_router_url", ""))
        f.addRow("Endpoint 9Router:", self.nr_url)
        self.ol_url = QLineEdit()
        self.ol_url.setText(self.settings.get("ollama_url", ""))
        f.addRow("Endpoint Ollama:", self.ol_url)
        row = QHBoxLayout()
        self.ol_model = QLineEdit()
        self.ol_model.setText(self.settings.get("ollama_model", ""))
        self.ol_model.setPlaceholderText("vd llama3.1, qwen2.5…")
        row.addWidget(self.ol_model, 1)
        btn_check = QPushButton("Kiểm tra kết nối")
        btn_check.clicked.connect(self.check_ollama)
        row.addWidget(btn_check)
        f.addRow("Model Ollama:", row)
        self.llm_temp = QDoubleSpinBox()
        self.llm_temp.setRange(0.0, 1.0)
        self.llm_temp.setSingleStep(0.05)
        self.llm_temp.setValue(float(self.settings.get("llm_temperature", 0.2)))
        f.addRow("Temperature LLM:", self.llm_temp)
        self.tr_batch = QSpinBox()
        self.tr_batch.setRange(1, 100)
        self.tr_batch.setValue(int(self.settings.get("translate_batch", 20)))
        f.addRow("Số câu / request dịch:", self.tr_batch)
        f.addRow(QLabel("Để trống API key 9Router nếu chỉ dùng Ollama local."))
        self.tabs.addTab(tab, "Dịch thuật")

    def check_ollama(self) -> None:
        import requests
        url = self.ol_url.text().strip().rstrip("/")
        try:
            r = requests.get(f"{url}/api/tags", timeout=8)
            r.raise_for_status()
            models = [m.get("name", "?")
                      for m in r.json().get("models", [])]
            hint = ("Các model đã kéo: " + ", ".join(models)
                    if models else "Chưa kéo model nào.")
            info_box(self, "Ollama chạy tốt",
                     f"Kết nối được tới {url}.\n{hint}\n\n"
                     "Nhập tên model vào ô Model Ollama rồi bấm Lưu.")
        except Exception as e:  # noqa: BLE001
            error_box(self, "Không kết nối được Ollama",
                      f"{e}\n\nCách khắc phục:\n"
                      "1. Mở Ollama (chạy lệnh: ollama serve)\n"
                      "2. Kéo model: ollama pull <tên-model> "
                      "(vd ollama pull llama3.1)\n"
                      "3. Kiểm tra lại endpoint ở ô trên.")

    # -------------------------------------------------------------- tab ASR
    def _build_asr_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        self.asr_model = QComboBox()
        self.asr_model.setEditable(True)
        self.asr_model.addItem(str(self.settings.get("asr_model")))
        self.asr_model.setCurrentText(str(self.settings.get("asr_model")))
        f.addRow("Model ASR:", self.asr_model)
        self.vad_model = QLineEdit(self.settings.get("vad_model", ""))
        f.addRow("Model VAD:", self.vad_model)
        self.punc_model = QLineEdit(self.settings.get("punc_model", ""))
        f.addRow("Model dấu câu:", self.punc_model)
        self.spk_model = QLineEdit(self.settings.get("spk_model", ""))
        f.addRow("Model tách loa:", self.spk_model)
        self.asr_conf = QDoubleSpinBox()
        self.asr_conf.setRange(0.0, 1.0)
        self.asr_conf.setSingleStep(0.05)
        self.asr_conf.setValue(float(self.settings.get("asr_confidence_low", 0.5)))
        f.addRow("Ngưỡng confidence thấp:", self.asr_conf)
        f.addRow(QLabel("Câu nào ASR nghe dưới ngưỡng này sẽ được đánh dấu "
                       "để bạn kiểm tra kỹ ở màn duyệt."))
        self.tabs.addTab(tab, "Nhận dạng (ASR)")

    # ------------------------------------------------------------ tab giọng
    def _build_voice_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        self.pitch_male = QDoubleSpinBox()
        self.pitch_male.setRange(50, 400)
        self.pitch_male.setValue(float(self.settings.get("pitch_male_max_hz", 160)))
        f.addRow("Pitch tối đa của nam (Hz):", self.pitch_male)
        self.pitch_female = QDoubleSpinBox()
        self.pitch_female.setRange(50, 400)
        self.pitch_female.setValue(
            float(self.settings.get("pitch_female_min_hz", 165)))
        f.addRow("Pitch tối thiểu của nữ (Hz):", self.pitch_female)
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
        self.tabs.addTab(tab, "Giọng đọc & Lồng tiếng")

    # ------------------------------------------------------------ tab video
    def _build_video_tab(self) -> None:
        tab = QWidget()
        f = QFormLayout(tab)
        self.sub_mode = QComboBox()
        self.sub_mode.addItem("Gắn cứng vào video", "burn")
        self.sub_mode.addItem("Xuất file .srt rời", "srt")
        cur = self.settings.get("sub_mode", "burn")
        self.sub_mode.setCurrentIndex(0 if cur == "burn" else 1)
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
        f.addRow(QLabel("CRF càng nhỏ video càng nét (file càng nặng)."))
        row = QHBoxLayout()
        self.ffmpeg_path = QLineEdit(self.settings.get("ffmpeg_path", "ffmpeg"))
        row.addWidget(self.ffmpeg_path, 1)
        btn_browse = QPushButton("Chọn…")
        btn_browse.clicked.connect(self.browse_ffmpeg)
        row.addWidget(btn_browse)
        f.addRow("Đường dẫn FFmpeg:", row)
        self.tabs.addTab(tab, "Video & Phụ đề")

    def browse_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn font phụ đề",
            "", "Font (*.ttf *.otf *.ttc);;Tất cả (*.*)")
        if path:
            self.sub_font.setText(path)

    def browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ffmpeg")
        if path:
            self.ffmpeg_path.setText(path)

    # --------------------------------------------------------- tab tên riêng
    def _build_names_tab(self) -> None:
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(QLabel(
            "Danh sách tên riêng (mỗi dòng một tên) — prompt dịch sẽ giữ "
            "nguyên/phiên âm Hán-Việt các tên này, không dịch nghĩa:"))
        self.names_edit = QPlainTextEdit()
        self.names_edit.setPlainText(
            "\n".join(self.settings.get("proper_nouns", [])))
        lay.addWidget(self.names_edit)
        self.tabs.addTab(tab, "Tên riêng")

    # ------------------------------------------------------------------ lưu
    def restore_defaults(self) -> None:
        self.nr_key.setText(str(DEFAULTS["nine_router_key"]))
        self.nr_model.setText(str(DEFAULTS["nine_router_model"]))
        self.nr_url.setText(str(DEFAULTS["nine_router_url"]))
        self.ol_url.setText(str(DEFAULTS["ollama_url"]))
        self.ol_model.setText(str(DEFAULTS["ollama_model"]))
        self.llm_temp.setValue(float(DEFAULTS["llm_temperature"]))
        self.tr_batch.setValue(int(DEFAULTS["translate_batch"]))
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
        self.sub_mode.setCurrentIndex(0 if DEFAULTS["sub_mode"] == "burn" else 1)
        self.sub_font.setText(str(DEFAULTS["sub_font"]))
        self.sub_font_size.setValue(int(DEFAULTS["sub_font_size"]))
        self.sub_font_color.setText(str(DEFAULTS["sub_font_color"]))
        self.crf.setValue(int(DEFAULTS["crf"]))
        self.ffmpeg_path.setText(str(DEFAULTS["ffmpeg_path"]))
        self.names_edit.setPlainText("")

    def save(self) -> None:
        if self.pitch_male.value() >= self.pitch_female.value():
            error_box(self, "Ngưỡng pitch không hợp lệ",
                      "Pitch tối đa của nam phải NHỎ HƠN pitch tối thiểu "
                      "của nữ (giọng nam trầm hơn giọng nữ).")
            return
        names = [ln.strip() for ln in
                 self.names_edit.toPlainText().splitlines() if ln.strip()]
        self.settings.update({
            "nine_router_key": self.nr_key.text().strip(),
            "nine_router_model": self.nr_model.text().strip(),
            "nine_router_url": self.nr_url.text().strip() or
            DEFAULTS["nine_router_url"],
            "ollama_url": self.ol_url.text().strip() or
            DEFAULTS["ollama_url"],
            "ollama_model": self.ol_model.text().strip(),
            "llm_temperature": self.llm_temp.value(),
            "translate_batch": self.tr_batch.value(),
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
            "sub_font": self.sub_font.text().strip(),
            "sub_font_size": self.sub_font_size.value(),
            "sub_font_color": self.sub_font_color.text().strip().lstrip("#"),
            "crf": self.crf.value(),
            "ffmpeg_path": self.ffmpeg_path.text().strip() or "ffmpeg",
            "proper_nouns": names,
        })
        self.settings.save()
        info_box(self, "Đã lưu", "Đã lưu cài đặt.")
        self.accept()
