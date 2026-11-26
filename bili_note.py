#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 站视频 → Obsidian 笔记（一条龙）：元数据 / 关键帧 / 热评 / 本地 ASR 转写。

用法:
    python bili_note.py --bvid BV1kdx96REn3
    python bili_note.py --bvid BV1kdx96REn3 BV1S84g62EtU --outdir "D:\\tmp\\notes"
    python bili_note.py --bvid BV1ffxJ69EdQ --no-audio      # 不下载音频/不转写

依赖：httpx、Pillow、faster-whisper（本机已装，离线模型 small）、ffmpeg。
"""
import argparse
import datetime
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx
from PIL import Image
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

VAULT = Path(str(VAULT_DIR))
NOTE_DIR = VAULT / "AI工具精选" / "视频"
SHOT_DIR = VAULT / "90_附件" / "截图" / "AI工具"
WORK = Path(str(BILI_LOGS_DIR))

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"
H = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}


def gj(client, url, **params):
    r = client.get(url, params=params or None, timeout=60)
    r.raise_for_status()
    return r.json()


def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def fetch_frames(client, bvid, cid, dur, limit=3):
    try:
        meta = (gj(client, "https://api.bilibili.com/x/player/videoshot",
                   bvid=bvid, cid=cid, index=1).get("data") or {})
    except Exception:
        return []
    xs, ys = meta.get("img_x_len"), meta.get("img_y_len")
    w, h = meta.get("img_x_size"), meta.get("img_y_size")
    stamps = meta.get("index") or []
    if not (xs and ys and stamps):
        return []
    per = xs * ys
    picked, files = [], []
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    for i, frac in enumerate([0.15, 0.55, 0.85][:limit], 1):
        idx = min(range(len(stamps)), key=lambda k: abs(stamps[k] - dur * frac))
        sheet, pos = idx // per, idx % per
        if sheet >= len(meta["image"]):
            continue
        url = "https:" + meta["image"][sheet]
        im = Image.open(io.BytesIO(client.get(url, timeout=120).content)).convert("RGB")
        left, top = (pos % xs) * w, (pos // xs) * h
        frame = im.crop((left, top, left + w, top + h))
        name = f"{bvid}_{i}.jpg"
        frame.save(SHOT_DIR / name, quality=88)
        files.append(name)
        picked.append(stamps[idx])
    return files


def fetch_comments(client, aid, limit=6):
    try:
        d = gj(client, "https://api.bilibili.com/x/v2/reply", type=1, oid=aid, sort=2, ps=12)
    except Exception:
        return []
    out = []
    for r in ((d.get("data") or {}).get("replies") or [])[:limit]:
        txt = (r.get("content") or {}).get("message") or ""
        if txt.strip():
            out.append({"user": (r.get("member") or {}).get("uname"),
                        "like": r.get("like"),
                        "text": txt.replace("\n", " ").strip()})
    return out


def fetch_audio(client, bvid, cid):
    d = gj(client, "https://api.bilibili.com/x/player/playurl", bvid=bvid, cid=cid, fnval=16, qn=64)
    dash = (d.get("data") or {}).get("dash") or {}
    audios = sorted(dash.get("audio") or [], key=lambda a: a.get("bandwidth", 0), reverse=True)
    if not audios:
        return None
    WORK.mkdir(parents=True, exist_ok=True)
    m4s = WORK / f"{bvid}.m4s"
    m4s.write_bytes(client.get(audios[0]["baseUrl"], timeout=180).content)
    wav = WORK / f"{bvid}.wav"
    subprocess.run(["ffmpeg", "-y", "-i", str(m4s), "-ar", "16000", "-ac", "1", str(wav)],
                   capture_output=True, check=True)
    return wav


def transcribe(wav):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8", local_files_only=True)
    segs, _info = model.transcribe(str(wav), language="zh", vad_filter=True,
                                   beam_size=1, condition_on_previous_text=False)
    return [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
            for s in segs if s.text.strip()]


def build_note(meta, frames, comments, segs, with_audio):
    title = meta["title"]
    desc = (meta.get("desc") or "").strip()
    dur = mmss(meta.get("duration") or 0)
    tags = re.findall(r"#([^\s#]+)", desc)
    up = meta.get("owner") or ""
    stat = meta.get("stat") or {}
    L = ["---", f"UP: {up}", f"BV: {meta['bvid']}", "类型: 视频笔记",
         f"tags: [AI工具, {up}]", f"日期: {datetime.date.today().isoformat()}", "---", "",
         f"# {title}", "",
         f"> [!info] UP：{up} ｜ 时长 {dur} ｜ [原视频](https://www.bilibili.com/video/{meta['bvid']}) ｜ "
         f"播放 {stat.get('view', '-')} · 点赞 {stat.get('like', '-')} ｜ 返回 [[_AI工具精选索引]]", "",
         "## 简介", ""]
    L += ["> " + x for x in (desc.splitlines() if desc else ["（作者未填简介）"]) if x.strip()]
    L.append("")
    if tags:
        L += ["## 标签", "", " ".join(f"`{t}`" for t in tags[:12]), ""]
    L += ["## 要点", "",
          "> 本条由 `bili_note.py` 自动生成，**没有做摘要**；要点请从下方转写里提炼（或让 AI 二次处理）。", ""]
    if frames:
        L += ["## 关键帧", ""]
        for f in frames:
            L += [f"![[{f}]]", ""]
    if comments:
        L += ["## 评论区", ""]
        for c in comments:
            L += [f"- **{c['user']}**（👍 {c['like']}）：{c['text']}"]
        L.append("")
    L += ["## 转写全文", ""]
    if not with_audio:
        L += ["> 本次用 `--no-audio` 跳过转写。", ""]
    elif not segs:
        L += ["> 本地 ASR 没识别到人声（可能是纯音乐/演示音）。", ""]
    else:
        L += ["> 本地 ASR（faster-whisper small，CPU），**可能有错别字**；时间戳为音频内位置。", ""]
        for s in segs:
            L.append(f"- `{mmss(s['start'])}` {s['text']}")
        L.append("")
    L += ["返回 [[_AI工具精选索引]]", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", nargs="+", required=True)
    ap.add_argument("--outdir", default=str(NOTE_DIR))
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument("--pause-ocr", action="store_true",
                    help="转写期间暂停 OCR（跑完自动恢复），避免 CPU 抢不过")
    a = ap.parse_args()
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if a.pause_ocr and not a.no_audio:
        ocr_ctl("stop")
    try:
        run_all(a, outdir)
    finally:
        if a.pause_ocr and not a.no_audio:
            ocr_ctl("resume")
    return 0


def ocr_ctl(mode):
    """暂停/恢复 OCR，给 ASR 让出 CPU。失败不致命。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", str(HOME / "ocr_turbo.ps1"), "-Mode", mode],
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        tail = ((r.stdout or "").strip().splitlines() or [""])[-1]
        print(f"  ocr {mode}: {tail[:80]}")
    except Exception as e:
        print(f"  ocr {mode} failed: {type(e).__name__}")


def run_all(a, outdir):

    with httpx.Client(headers=H, follow_redirects=True, trust_env=False) as client:
        for bvid in a.bvid:
            print(f"== {bvid}")
            try:
                v = gj(client, "https://api.bilibili.com/x/web-interface/view", bvid=bvid)
                d = v.get("data") or {}
            except Exception as e:
                print(f"  view failed: {e}")
                continue
            meta = {"bvid": bvid, "title": d.get("title"), "owner": (d.get("owner") or {}).get("name"),
                    "duration": d.get("duration"), "desc": d.get("desc"),
                    "stat": {k: (d.get("stat") or {}).get(k) for k in ("view", "like")}}
            cid, aid = d.get("cid"), d.get("aid")
            frames = fetch_frames(client, bvid, cid, d.get("duration") or 0)
            comments = fetch_comments(client, aid)
            segs = []
            if not a.no_audio:
                try:
                    wav = fetch_audio(client, bvid, cid)
                    segs = transcribe(wav) if wav else []
                    print(f"  asr segments: {len(segs)}")
                except Exception as e:
                    print(f"  asr failed: {type(e).__name__} {e}")
            note = build_note(meta, frames, comments, segs, not a.no_audio)
            path = outdir / (re.sub(r'[\\/:*?"<>|]', "／", meta["title"]) + ".md")
            path.write_text(note, encoding="utf-8", newline="\n")
            print(f"  wrote {path.name} ({len(note)} chars, frames={len(frames)}, comments={len(comments)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
