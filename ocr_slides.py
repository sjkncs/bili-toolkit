#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对讲座场景帧做 OCR，输出 {frame: {text, lines}}，并做文本层面的去重（相邻帧内容相同只留一张）。"""
import glob
import json
import os
import time

import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

W = str(BILI_LOGS_DIR / "video")
OUT = os.path.join(W, "frames")
RES = os.path.join(W, "frames_ocr.json")


def main():
    files = sorted(glob.glob(os.path.join(OUT, "*.jpg")))
    data = {}
    if os.path.exists(RES):
        try:
            data = json.load(open(RES, encoding="utf-8"))
        except Exception:
            data = {}
    eng = RapidOCR()
    t0 = time.time()
    for i, f in enumerate(files, 1):
        key = os.path.basename(f)
        if key in data:
            continue
        img = np.array(Image.open(f).convert("RGB"))
        r, _ = eng(img)
        lines = [x[1].strip() for x in (r or []) if x[1].strip()]
        data[key] = {"lines": lines, "text": "\n".join(lines)}
        if i % 10 == 0 or i == len(files):
            json.dump(data, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"{i}/{len(files)}  {time.time()-t0:.0f}s", flush=True)
    json.dump(data, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("DONE", len(data), flush=True)


if __name__ == "__main__":
    main()
