#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 站视频一条龙：docx/链接 → 笔记（元数据 / 关键帧 / 热评 / 分块并行 ASR / 简体化 / 索引）。

用法:
    python bili_pipeline.py --docx "C:\\path\\list.docx"
    python bili_pipeline.py --links https://b23.tv/xxxx BV1xxxxxxxxx
    python bili_pipeline.py --docx list.docx --force        # 已存在也重做
    python bili_pipeline.py --docx list.docx --workers 4 --chunk 600

约定:
- 笔记落在 <vault>\\AI工具精选\\视频\\<标题>.md，已存在则跳过（--force 覆盖）
- 转写走分块 + 多进程（每块 10 分钟），短片中块数少自然就快
- 繁体自动转简体（opencc t2s）
- 自动追加到 _AI工具精选索引
"""
import argparse
import glob
import json
import os
import re
import subprocess
import time
import zipfile
from multiprocessing import Process

import httpx
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

VAULT = str(VAULT_DIR)
NOTEDIR = os.path.join(VAULT, "AI工具精选", "视频")
INDEX = os.path.join(VAULT, "AI工具精选", "_AI工具精选索引.md")
SHOT = os.path.join(VAULT, "90_附件", "截图", "AI工具")
WORK = str(BILI_LOGS_DIR)
MODEL = str(WHISPER_MODEL)
H = {"User-Agent": "Mozilla/5.0 Chrome/131.0.0.0", "Referer": "https://www.bilibili.com/"}


def mmss(s):
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def safe(n):
    return re.sub(r'[\\/:*?"<>|]', "／", n)


# ---------- 链接解析 ----------
def links_from_docx(path):
    try:
        import docx
        txt = "\n".join(p.text for p in docx.Document(path).paragraphs)
    except Exception:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml))
    found = re.findall(r"https?://b23\.tv/[A-Za-z0-9]+|https?://www\.bilibili\.com/video/BV[0-9A-Za-z]{10}|BV[0-9A-Za-z]{10}", txt)
    out, seen = [], set()
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def resolve(c, link):
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", link):
        return link
    r = c.get(link)
    m = re.search(r"(BV[0-9A-Za-z]{10})", str(r.url))
    return m.group(1) if m else None


# ---------- 音频与转写 ----------
def get_audio(c, bv, cid):
    os.makedirs(WORK, exist_ok=True)
    m4s = os.path.join(WORK, bv + ".m4s")
    if not (os.path.exists(m4s) and os.path.getsize(m4s) > 100_000):
        d = c.get("https://api.bilibili.com/x/player/playurl",
                  params={"bvid": bv, "cid": cid, "fnval": 4048, "qn": 80}).json()
        au = sorted(((d.get("data") or {}).get("dash") or {}).get("audio") or [],
                    key=lambda a: a.get("bandwidth", 0), reverse=True)
        if not au:
            return None
        open(m4s, "wb").write(c.get(au[0]["baseUrl"], timeout=600).content)
    return m4s


def split_chunks(bv, chunk):
    src = os.path.join(WORK, bv + ".m4s")
    out_dir = os.path.join(WORK, bv + "_chunks")
    os.makedirs(out_dir, exist_ok=True)
    if not glob.glob(os.path.join(out_dir, "*.wav")):
        subprocess.run(["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
                        "-f", "segment", "-segment_time", str(chunk),
                        os.path.join(out_dir, "chunk_%03d.wav")],
                       capture_output=True, check=True)
    return out_dir


def _worker(files, bv, chunk, idx, lang):
    from faster_whisper import WhisperModel
    m = WhisperModel(MODEL, device="cpu", compute_type="int8")
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        out = os.path.join(WORK, f"{bv}.part.{base}.json")
        if os.path.exists(out):
            continue
        segs, info = m.transcribe(f, language=lang, vad_filter=True, beam_size=1,
                                  condition_on_previous_text=False)
        data = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
                for s in segs if s.text.strip()]
        json.dump({"chunk": base, "lang": info.language, "segments": data},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  [w{idx}] {base} segs={len(data)}", flush=True)


def transcribe(bv, chunk, workers, lang):
    asr = os.path.join(WORK, bv + ".asr.json")
    if os.path.exists(asr):
        return json.load(open(asr, encoding="utf-8"))["segments"]
    d = split_chunks(bv, chunk)
    files = sorted(glob.glob(os.path.join(d, "*.wav")))
    n = min(workers, len(files)) or 1
    buckets = [files[i::n] for i in range(n)]
    procs = [Process(target=_worker, args=(b, bv, chunk, i, lang)) for i, b in enumerate(buckets) if b]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    merged = []
    for f in glob.glob(os.path.join(WORK, f"{bv}.part.*.json")):
        rec = json.load(open(f, encoding="utf-8"))
        off = int(rec["chunk"].split("_")[-1]) * chunk
        for s in rec["segments"]:
            merged.append({"start": round(s["start"] + off, 1), "end": round(s["end"] + off, 1),
                           "text": s["text"]})
    merged.sort(key=lambda x: x["start"])
    json.dump({"bvid": bv, "segments": merged}, open(asr, "w", encoding="utf-8"), ensure_ascii=False)
    return merged


# ---------- 素材 ----------
def frames(c, bv, cid, dur, n=4):
    try:
        sp = c.get("https://api.bilibili.com/x/player/videoshot",
                   params={"bvid": bv, "cid": cid, "index": 1}).json()["data"]
    except Exception:
        return []
    st = sp.get("index") or []
    if not st or not (sp.get("image") or []):
        return []
    from io import BytesIO
    from PIL import Image
    xs, ys, w, h = sp["img_x_len"], sp["img_y_len"], sp["img_x_size"], sp["img_y_size"]
    per = xs * ys
    os.makedirs(SHOT, exist_ok=True)
    out = []
    for i, fr in enumerate([0.05, 0.3, 0.6, 0.85][:n], 1):
        idx = min(range(len(st)), key=lambda k: abs(st[k] - dur * fr))
        sheet, pos = idx // per, idx % per
        if sheet >= len(sp["image"]):
            continue
        im = Image.open(BytesIO(c.get("https:" + sp["image"][sheet], timeout=120).content)).convert("RGB")
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


def build_note(meta, fr, cm, segs):
    L = ["---", f"UP: {meta['owner']}", f"BV: {meta['bv']}", "类型: 视频笔记",
         f"tags: [AI工具, {meta['owner']}]", f"日期: {time.strftime('%Y-%m-%d')}", "---", "",
         f"# {meta['title']}", "",
         f"> [!info] UP：{meta['owner']} ｜ 时长 {mmss(meta['dur'])} ｜ "
         f"[原视频](https://www.bilibili.com/video/{meta['bv']}) ｜ 播放 {meta['view']} ｜ "
         f"返回 [[_AI工具精选索引]]", "",
         "## 简介", ""]
    desc = (meta.get("desc") or "").strip()
    L += ["> " + x for x in (desc.splitlines() if desc else ["（作者未填简介）"]) if x.strip()]
    L += ["", "## 要点", "",
          "> 本条由 `bili_pipeline.py` 自动生成，**没有做摘要**；下面是原始材料（转写/评论），要点请据此提炼。", ""]
    if fr:
        L += ["## 关键帧", ""]
        for f in fr:
            L += [f"![[{f['file']}]]  <!-- {mmss(f['t'])} -->", ""]
    if cm:
        L += ["## 评论区", ""]
        for x in cm:
            L += [f"- **{x['user']}**（👍 {x['like']}）：{x['text']}"]
        L.append("")
    L += ["## 转写全文", ""]
    if segs:
        L += ["> 本地 ASR（faster-whisper small，分块并行），**可能有错别字**；时间戳为音频内位置。", ""]
        for s in segs:
            L.append(f"- `{mmss(s['start'])}` {s['text']}")
        L.append("")
    else:
        L += ["> 没有识别到人声（可能是纯音乐 / 展示片）。", ""]
    L += ["返回 [[_AI工具精选索引]]", ""]
    return "\n".join(L)


def to_simplified(text):
    try:
        from opencc import OpenCC
        return OpenCC("t2s").convert(text)
    except Exception:
        return text


def add_index(meta):
    if not os.path.exists(INDEX):
        return
    t = open(INDEX, encoding="utf-8").read()
    link = f"[[{meta['title']}]]"
    if link in t:
        return
    row = f"| {meta['owner']} | {link} | {mmss(meta['dur'])} |"
    open(INDEX, "w", encoding="utf-8", newline="\n").write(t.rstrip() + "\n" + row + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docx", default="")
    ap.add_argument("--links", nargs="*", default=[])
    ap.add_argument("--chunk", type=int, default=600)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--lang", default=None, help="默认自动检测；可强制 zh/en")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()

    links = list(a.links)
    if a.docx:
        links += links_from_docx(a.docx)
    if not links:
        print("没有找到链接"); return 2
    print(f"共 {len(links)} 条链接")

    os.makedirs(NOTEDIR, exist_ok=True)
    ok = skip = fail = 0
    with httpx.Client(headers=H, follow_redirects=True, timeout=600, trust_env=False) as c:
        for link in links:
            bv = resolve(c, link)
            if not bv:
                print(f"[skip] 无法解析: {link}"); fail += 1; continue
            d = c.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bv}).json()["data"]
            meta = {"bv": bv, "title": d["title"], "owner": (d["owner"] or {}).get("name"),
                    "dur": d["duration"], "desc": d.get("desc") or "",
                    "view": (d.get("stat") or {}).get("view")}
            path = os.path.join(NOTEDIR, safe(meta["title"]) + ".md")
            if os.path.exists(path) and not a.force:
                print(f"[skip] 已存在: {meta['title'][:40]}"); skip += 1; continue
            print(f"[run ] {bv} {mmss(meta['dur'])} {meta['title'][:40]}", flush=True)
            segs = []
            if not a.no_asr:
                if get_audio(c, bv, d["cid"]):
                    segs = transcribe(bv, a.chunk, a.workers, a.lang)
                else:
                    print("  无音频流")
            fr = frames(c, bv, d["cid"], d["duration"])
            cm = comments(c, d["aid"])
            text = to_simplified(build_note(meta, fr, cm, segs))
            open(path, "w", encoding="utf-8", newline="\n").write(text)
            add_index(meta)
            print(f"[ok  ] {os.path.basename(path)} segs={len(segs)} frames={len(fr)} comments={len(cm)}")
            ok += 1
    print(f"完成：新增 {ok} / 跳过 {skip} / 失败 {fail}")


if __name__ == "__main__":
    raise SystemExit(main())
