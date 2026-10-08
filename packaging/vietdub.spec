# -*- mode: python ; coding: utf-8 -*-
# VietDub — PyInstaller spec (chế độ onedir, target chính: Windows 11 x64)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (xem LICENSE ở thư mục gốc)
"""
ĐÓNG GÓI VietDub thành app chạy độc lập (không cần cài Python).

Cách build trên Windows (máy Tony):
  1. Cài Python 3.10+ (python.org, tick "Add python.exe to PATH").
  2. Tải ffmpeg bản Windows (vd bản "release essentials" tại gyan.dev),
     chép ffmpeg.exe + ffprobe.exe vào thư mục packaging/bin/ (xem
     packaging/bin/README.txt).
  3. Trong thư mục vietdub/:
       pip install torch --index-url https://download.pytorch.org/whl/cpu
       pip install -r requirements.txt
       pip install pyinstaller
       pyinstaller packaging/vietdub.spec
  4. File chạy: dist\\VietDub\\VietDub.exe

LƯU Ý:
- Model FunASR KHÔNG bundle trong exe (nặng ~1.3GB). Lần đầu chạy,
  app tự tải về %APPDATA%\\VietDub\\models\\ (chỉ 1 lần, cần mạng).
  Xem asr/funasr_adapter.py (hàm load): MODELSCOPE_CACHE được trỏ
  về thư mục đó trước khi tải.
- Validation trên Linux: chạy cùng spec này sẽ build ra binary Linux
  (không phải .exe) — mục đích chứng minh spec không lỗi cú pháp /
  không thiếu module. .exe Windows thật do Tony build trên máy anh.

Biến môi trường hỗ trợ:
  VIETDUB_CONSOLE=1  -> build có cửa sổ console (debug; mặc định 0 = app GUI).
"""
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

# SPECPATH = thư mục chứa file spec này (packaging/); project root là cấp trên.
ROOT = Path(SPECPATH).parent  # noqa: F821 - do PyInstaller cung cấp khi build
BIN_DIR = ROOT / "packaging" / "bin"

# --- binaries: ffmpeg/ffprobe kèm theo -------------------------------------
# Windows: ffmpeg.exe + ffprobe.exe (Tony tải về đặt vào packaging/bin/).
# Linux (build validation): ffmpeg + ffprobe nếu có — thiếu cũng không lỗi.
binaries = []
if BIN_DIR.is_dir():
    for cand in sorted(BIN_DIR.iterdir()):
        if cand.is_file() and cand.name.lower().startswith(("ffmpeg", "ffprobe")):
            binaries.append((str(cand), "."))  # đặt cạnh VietDub.exe
            print(f"[vietdub.spec] kèm binary: {cand.name}")
if not binaries:
    print("[vietdub.spec] CẢNH BÁO: packaging/bin/ trống — build vẫn chạy, "
          "nhưng app đóng gói sẽ không có ffmpeg kèm theo. "
          "Trên Windows hãy tải ffmpeg.exe + ffprobe.exe vào packaging/bin/ "
          "trước khi build (xem packaging/bin/README.txt).")

# --- hidden imports: các module load động mà PyInstaller không tự thấy ------
# funasr + modelscope load model/pipeline động -> collect toàn bộ submodule.
hiddenimports = (
    collect_submodules("funasr")
    + collect_submodules("modelscope")
    + [
        # torch runtime (hook-torch của PyInstaller lo phần lớn, liệt kê thêm
        # cho chắc các backend load động)
        "torch", "torch.nn", "torch._C",
        # fbank backend cho FunASR (1 trong 2, tùy máy cài gì)
        "kaldi_native_fbank", "torchaudio",
        # audio / pitch
        "librosa", "soundfile", "scipy", "scipy.signal",
        "sklearn", "numba", "soxr",
        "pooch", "lazy_loader", "msgpack",
        # TTS
        "edge_tts", "gtts",
        # translation / http
        "openai", "requests", "urllib3",
        # yt-dlp (load extractor động)
        "yt_dlp",
        # funasr deps load động
        "hydra", "omegaconf",
        "jieba", "jaconv", "jamo", "kaldiio",
        "rapidfuzz", "regex", "tiktoken", "torch_complex",
        "transformers", "tensorboardX", "oss2",
        "websockets",
        # modelscope deps (requirements.txt ghi chú: upstream không khai báo)
        "addict", "datasets", "PIL", "simplejson",
        "huggingface_hub", "safetensors", "filelock",
        "yaml", "tqdm", "einops", "sentencepiece",
        # UI
        "PySide6",
        "numpy",
    ]
)

# Loại bớt cho nhẹ (không dùng tới trong app)
excludes = [
    "tkinter", "unittest", "pydoc", "doctest",
    "matplotlib",  # không phải dep của VietDub
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# GUI app trên Windows: không hiện cửa sổ console.
# Đặt VIETDUB_CONSOLE=1 khi build để debug (hiện console + log).
_console = os.environ.get("VIETDUB_CONSOLE", "0") == "1"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VietDub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX hay false-positive antivirus trên Windows -> tắt
    console=_console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VietDub",  # -> dist/VietDub/VietDub.exe (Windows)
)
