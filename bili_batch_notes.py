#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量：B 站视频 → 笔记（元数据 / 关键帧 / 热评 / 本地 ASR）。模型只加载一次。

用法:
    python bili_batch_notes.py --bvid BV1cV4A6LESb BV1NZW36iEgW --no-asr
    python bili_batch_notes.py --bvid BV1cV4A6LESb BV1XQWb6YEDP BV1NZW36iEgW
长视频（>20min）建议先用 bili_long_asr.py 分块转写，再 --asr-json <path>。
"""
import argparse
import io
import json
import os
import re
import subprocess
from datetime import date

import httpx
from PIL import Image
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

VAULT = str(VAULT_DIR)
NOTEDIR = os.path.join(VAULT, "AI工具精选", "视频")
SHOT = os.path.join(VAULT, "90_附件", "截图", "AI工具")
WORK = str(BILI_LOGS_DIR)
MODEL = str(WHISPER_MODEL)
H = {"User-Agent": "Mozilla/5.0 Chrome/131.0.0.0", "Referer": "https://www.bilibili.com/"}


def mmss(s):
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def safe(n):
    return re.sub(r'[\\/:*?"<>|]', "／", n)


def frames(c, bv, cid, dur, n=4):
    try:
        sp = c.get("https://api.bilibili.com/x/player/videoshot",
                   params={"bvid": bv, "cid": cid, "index": 1}).json()["data"]
    except Exception:
        return []
    xs, ys, w, h = sp["img_x_len"], sp["img_y_len"], sp["img_x_size"], sp["img_y_size"]
    st, per = sp.get("index") or [], xs * ys
    if not st or not (sp.get("image") or []):
        return []
    fracs = [0.05, 0.3, 0.6, 0.85][:n]
    out = []
    os.makedirs(SHOT, exist_ok=True)
    for i, fr in enumerate(fracs, 1):
        idx = min(range(len(st)), key=lambda k: abs(st[k] - dur * fr))
        sheet, pos = idx // per, idx % per
        if sheet >= len(sp["image"]):
            continue
        im = Image.open(io.BytesIO(c.get("https:" + sp["image"][sheet], timeout=120).content)).convert("RGB")
        left, top = (pos % xs) * w, (pos // xs) * h
        name = f"{bv}_{i}.jpg"
        im.crop((left, top, left + w, top + h)).save(os.path.join(SHOT, name), quality=88)
        out.append({"file": name, "t": st[idx]})
    return out


def comments(c, aid, k=8):
    try:
        d = c.get("https://api.bilibili.com/x/v2/reply",
                  params={"type": 1, "oid": aid, "sort": 2, "ps": 20}).json()
    except Exception:
        return []
    out = []
    for r in ((d.get("data") or {}).get("replies") or [])[:k]:
        t = (r.get("content") or {}).get("message") or ""
        if t.strip():
            out.append({"user": (r.get("member") or {}).get("uname"), "like": r.get("like"),
                        "text": t.replace("\n", " ").strip()})
    return out


def audio(c, bv, cid):
    d = c.get("https://api.bilibili.com/x/player/playurl",
              params={"bvid": bv, "cid": cid, "fnval": 16, "qn": 64}).json()
    au = sorted(((d.get("data") or {}).get("dash") or {}).get("audio") or [],
                key=lambda a: a.get("bandwidth", 0), reverse=True)
    if not au:
        return None
    os.makedirs(WORK, exist_ok=True)
    m4s = os.path.join(WORK, bv + ".m4s")
    if not os.path.exists(m4s) or os.path.getsize(m4s) < 100_000:
        open(m4s, "wb").write(c.get(au[0]["baseUrl"], timeout=300).content)
    wav = os.path.join(WORK, bv + ".wav")
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-y", "-i", m4s, "-ar", "16000", "-ac", "1", wav],
                       capture_output=True, check=True)
    return wav


def note(meta, fr, cm, segs, used_asr):
    t, dur = meta["title"], meta["dur"]
    L = ["---", f"UP: {meta['owner']}", f"BV: {meta['bv']}", "类型: 视频笔记",
         f"tags: [AI工具, {meta['owner']}]", f"日期: {date.today().isoformat()}", "---", "",
         f"# {t}", "",
         f"> [!info] UP：{meta['owner']} ｜ 时长 {mmss(dur)} ｜ "
         f"[原视频](https://www.bilibili.com/video/{meta['bv']}) ｜ 播放 {meta['view']} ｜ "
         f"返回 [[_AI工具精选索引]]", "",
         "## 简介", ""]
    desc = (meta.get("desc") or "").strip()
    L += ["> " + x for x in (desc.splitlines() if desc else ["（作者未填简介）"]) if x.strip()]
    L += ["", "## 要点", "",
          "> 本条由 `bili_batch_notes.py` 自动生成，**没有做摘要**；下面是原始材料（转写/评论），要点请据此提炼。", ""]
    if fr:
        L += ["## 关键帧", ""]
        for f in fr:
            L += [f"![[{f['file']}]]  <!-- {mmss(f['t'])} -->", ""]
    if cm:
        L += ["## 评论区", ""]
        for c in cm:
            L += [f"- **{c['user']}**（👍 {c['like']}）：{c['text']}"]
        L.append("")
    L += ["## 转写全文", ""]
    if not used_asr:
        L += ["> 本次跳过转写。", ""]
    elif not segs:
        L += ["> 没识别到人声。", ""]
    else:
        L += ["> 本地 ASR（faster-whisper small），**可能有错别字**；时间戳为音频内位置。", ""]
        for s in segs:
            L.append(f"- `{mmss(s['start'])}` {s['text']}")
        L.append("")
    L += ["返回 [[_AI工具精选索引]]", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", nargs="+", required=True)
    ap.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()
    os.makedirs(NOTEDIR, exist_ok=True)
    model = None
    with httpx.Client(headers=H, follow_redirects=True, timeout=300, trust_env=False) as c:
        for bv in a.bvid:
            d = c.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bv}).json()["data"]
            meta = {"bv": bv, "title": d["title"], "owner": (d["owner"] or {}).get("name"),
                    "dur": d["duration"], "desc": (d.get("desc") or ""),
                    "view": (d.get("stat") or {}).get("view")}
            cid, aid = d["cid"], d["aid"]
            fr = frames(c, bv, cid, d["duration"])
            cm = comments(c, aid)
            segs = []
            if not a.no_asr:
                wav = audio(c, bv, cid)
                if wav:
                    if model is None:
                        from faster_whisper import WhisperModel
                        model = WhisperModel(MODEL, device="cpu", compute_type="int8")
                    segs_it, info = model.transcribe(wav, language=None, vad_filter=True,
                                                     beam_size=1, condition_on_previous_text=False)
                    segs = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
                            for s in segs_it if s.text.strip()]
                    print(f"  lang={info.language} segs={len(segs)}", flush=True)
            text = note(meta, fr, cm, segs, not a.no_asr)
            p = os.path.join(NOTEDIR, safe(meta["title"]) + ".md")
            open(p, "w", encoding="utf-8", newline="\n").write(text)
            print(f"[ok] {bv} {meta['title'][:40]} -> {os.path.basename(p)} ({len(text)} chars, frames={len(fr)}, comments={len(cm)})", flush=True)


if __name__ == "__main__":
    main()
