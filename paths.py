# -*- coding: utf-8 -*-
"""集中管理路径：优先读环境变量，缺省沿用原作者机器布局。

可通过 .env / 系统环境变量覆盖：
    BILI_INDEX_HOME   工具根目录（默认 C:\\bili-index）
    OBSIDIAN_VAULT    Obsidian 库根（默认 <HOME>\\SONG的终极兵器）
    WHISPER_MODEL     faster-whisper 模型目录（默认 <HOME>\\models\\faster-whisper-small）
"""
import os
from pathlib import Path

HOME = Path(os.environ.get("BILI_INDEX_HOME", r"C:\bili-index"))
VAULT_DIR = Path(os.environ.get("OBSIDIAN_VAULT", str(HOME / "SONG的终极兵器")))
LOGS_DIR = HOME / "logs"
BILI_LOGS_DIR = LOGS_DIR / "bili"
OCR_LOGS_DIR = LOGS_DIR / "ocr"
WHISPER_MODEL = Path(os.environ.get("WHISPER_MODEL", str(HOME / "models" / "faster-whisper-small")))
SKILL_PROBE_DIR = LOGS_DIR / "skill_probe"
