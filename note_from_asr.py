#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用已生成的分块 ASR 结果（bili_long_asr.py 产出）补写一条视频笔记。"""
import argparse
import json
import os
import sys

sys.path.insert(0, str(HOME))
import httpx

import bili_batch_notes as B
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", required=True)
    ap.add_argument("--asr", required=True)
    a = ap.parse_args()
    segs = json.load(open(a.asr, encoding="utf-8"))["segments"]
    with httpx.Client(headers=B.H, follow_redirects=True, timeout=300, trust_env=False) as c:
        d = c.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": a.bvid}).json()["data"]
        meta = {"bv": a.bvid, "title": d["title"], "owner": (d["owner"] or {}).get("name"),
                "dur": d["duration"], "desc": (d.get("desc") or ""),
                "view": (d.get("stat") or {}).get("view")}
        cid, aid = d["cid"], d["aid"]
        fr = B.frames(c, a.bvid, cid, d["duration"])
        cm = B.comments(c, aid)
    text = B.note(meta, fr, cm, segs, True)
    p = os.path.join(B.NOTEDIR, B.safe(meta["title"]) + ".md")
    open(p, "w", encoding="utf-8", newline="\n").write(text)
    print(f"[ok] {a.bvid} -> {os.path.basename(p)} ({len(text)} chars, segs={len(segs)}, frames={len(fr)}, comments={len(cm)})")


if __name__ == "__main__":
    main()
