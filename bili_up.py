#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""整站批处理：某个 UP 的全部视频 → 笔记（断点续跑，模型只加载一次/进程）。

用法:
    python bili_up.py --mid 49683148 --limit 3          # 先试 3 条
    python bili_up.py --mid 49683148 --workers 4        # 全量（后台跑）
    python bili_up.py --mid 49683148 --force            # 已存在也重做

产物:
    <vault>/AI工具精选/视频/<outdir>/<标题>.md
    <vault>/AI工具精选/视频/<outdir>/_索引.md
    logs/bili_up_<mid>.jsonl   （每条一行进度）
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.parse
from multiprocessing import Process

import httpx

VAULT = str(VAULT_DIR)
WORK = str(BILI_LOGS_DIR)
MODEL = str(WHISPER_MODEL)
import uuid as _uuid
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)
_BAV = str(_uuid.uuid4()).upper() + "infoc"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
     "Referer": "https://www.bilibili.com/",
     "Cookie": f"buvid3={_BAV}; b_nut={int(time.time())}"}
MIXIN = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49, 33, 9, 42, 19, 29, 28,
         14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21,
         56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def mmss(s):
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def safe(n):
    return re.sub(r'[\\/:*?"<>|]', "／", n)[:90]


def wbi_sign(params, img_key, sub_key):
    mix = "".join((img_key + sub_key)[i] for i in MIXIN)[:32]
    p = dict(params)
    p["wts"] = int(time.time())
    q = urllib.parse.urlencode(sorted(p.items()))
    p["w_rid"] = hashlib.md5((q + mix).encode()).hexdigest()
    return p


def getjson(c, url, params=None):
    """容错取 JSON：B站风控时可能返回空 body 或 HTML。"""
    try:
        r = c.get(url, params=params or None)
        body = (r.content or b"").strip()
        if not body:
            return {"_status": r.status_code, "_empty": True}
        try:
            return r.json()
        except Exception:
            return {"_status": r.status_code, "_body": (r.text or "")[:200]}
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def list_all(c, mid, log, name="", tries=6):
    """枚举 UP 的全部投稿。
    主页 arc/search 现在对本机 IP 返回 412（request was banned），
    所以改用搜索接口按 pubdate 翻页 + 按 mid 过滤，实测能拿到几乎全部。"""
    nav = getjson(c, "https://api.bilibili.com/x/web-interface/nav")
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    if not name:
        name = str(mid)
    out, seen = [], set()
    page, num_pages = 1, 1
    while page <= max(1, min(num_pages, 50)):
        p = wbi_sign({"search_type": "video", "keyword": name, "order": "pubdate", "page": page}, img, sub)
        r = getjson(c, "https://api.bilibili.com/x/web-interface/wbi/search/type", p)
        waited = 0
        while (r.get("code") or 0) != 0 and waited < tries:
            wait = min(300, 30 * (2 ** waited))
            log(f"搜索第 {page} 页被限流（{r.get('code')}），{wait}s 后重试 {waited+1}/{tries}")
            time.sleep(wait)
            waited += 1
            r = getjson(c, "https://api.bilibili.com/x/web-interface/wbi/search/type", p)
        if (r.get("code") or 0) != 0:
            log(f"搜索第 {page} 页放弃：{r.get('code')}")
            break
        data = r.get("data") or {}
        num_pages = data.get("numPages") or num_pages
        res = data.get("result") or []
        if not res:
            break
        mine = [x for x in res if str(x.get("mid")) == str(mid)]
        for x in mine:
            bv = x.get("bvid")
            if bv and bv not in seen:
                seen.add(bv)
                out.append({"bvid": bv, "title": re.sub(r"<[^>]+>", "", x.get("title") or ""),
                            "length": x.get("duration"), "created": x.get("pubdate")})
        log(f"搜索第 {page}/{num_pages} 页：本 UP {len(mine)} 条，累计 {len(out)}")
        page += 1
        time.sleep(2.2)
    return out


# ---------- 单条视频 → 笔记 ----------
def one_video(c, model, bv, outdir, force, log):
    from io import BytesIO
    from PIL import Image
    d = (getjson(c, "https://api.bilibili.com/x/web-interface/view", {"bvid": bv}).get("data") or {})
    title = d["title"]
    path = os.path.join(outdir, safe(title) + ".md")
    if os.path.exists(path) and not force:
        return "skip", title, 0
    dur = d["duration"]
    cid, aid = d["cid"], d["aid"]
    # 音频
    m4s = os.path.join(WORK, bv + ".m4s")
    segs = []
    if not (os.path.exists(m4s) and os.path.getsize(m4s) > 100_000):
        pu = c.get("https://api.bilibili.com/x/player/playurl",
                   params={"bvid": bv, "cid": cid, "fnval": 16, "qn": 64}).json()
        au = sorted(((pu.get("data") or {}).get("dash") or {}).get("audio") or [],
                    key=lambda a: a.get("bandwidth", 0), reverse=True)
        if au:
            open(m4s, "wb").write(c.get(au[0]["baseUrl"], timeout=300).content)
    if os.path.exists(m4s):
        wav = os.path.join(WORK, bv + ".wav")
        if not os.path.exists(wav):
            subprocess.run(["ffmpeg", "-y", "-i", m4s, "-ar", "16000", "-ac", "1", wav],
                           capture_output=True)
        if os.path.exists(wav):
            it, info = model.transcribe(wav, language="zh", vad_filter=True, beam_size=1,
                                        condition_on_previous_text=False)
            segs = [{"start": round(s.start, 1), "text": s.text.strip()} for s in it if s.text.strip()]
    # 帧 + 评论
    fr = []
    try:
        sp = c.get("https://api.bilibili.com/x/player/videoshot",
                   params={"bvid": bv, "cid": cid, "index": 1}).json()["data"]
        st = sp.get("index") or []
        if st and (sp.get("image") or []):
            shotdir = os.path.join(VAULT, "90_附件", "截图", "远南岛")
            os.makedirs(shotdir, exist_ok=True)
            xs, ys, w, h = sp["img_x_len"], sp["img_y_len"], sp["img_x_size"], sp["img_y_size"]
            per = xs * ys
            for i, frac in enumerate([0.1, 0.6, 0.9][:3], 1):
                idx = min(range(len(st)), key=lambda k: abs(st[k] - dur * frac))
                sheet, pos = idx // per, idx % per
                if sheet >= len(sp["image"]):
                    continue
                im = Image.open(BytesIO(c.get("https:" + sp["image"][sheet], timeout=120).content)).convert("RGB")
                left, top = (pos % xs) * w, (pos // xs) * h
                name = f"{bv}_{i}.jpg"
                im.crop((left, top, left + w, top + h)).save(os.path.join(shotdir, name), quality=88)
                fr.append({"file": name, "t": st[idx]})
    except Exception:
        pass
    cm = []
    try:
        rp = c.get("https://api.bilibili.com/x/v2/reply", params={"type": 1, "oid": aid, "sort": 2, "ps": 20}).json()
        for r in ((rp.get("data") or {}).get("replies") or [])[:5]:
            t = (r.get("content") or {}).get("message") or ""
            if t.strip():
                cm.append({"user": (r.get("member") or {}).get("uname"), "like": r.get("like"),
                           "text": t.replace("\n", " ").strip()})
    except Exception:
        pass
    # 写笔记
    L = ["---", f"UP: {d['owner']['name']}", f"BV: {bv}", "类型: 视频笔记",
         f"tags: [AI工具, 远南岛]", f"日期: {time.strftime('%Y-%m-%d')}", "---", "",
         f"# {title}", "",
         f"> [!info] 时长 {mmss(dur)} ｜ [原视频](https://www.bilibili.com/video/{bv}) ｜ "
         f"播放 {(d.get('stat') or {}).get('view')} ｜ 返回 [[_索引]]", "",
         "## 简介", ""]
    desc = (d.get("desc") or "").strip()
    L += ["> " + x for x in (desc.splitlines() if desc else ["（无简介）"]) if x.strip()]
    if fr:
        L += ["", "## 关键帧", ""]
        for f in fr:
            L += [f"![[{f['file']}]]  <!-- {mmss(f['t'])} -->", ""]
    if cm:
        L += ["## 评论区", ""]
        for x in cm:
            L += [f"- **{x['user']}**（👍 {x['like']}）：{x['text']}"]
        L.append("")
    L += ["## 转写", ""]
    if segs:
        L += ["> 本地 ASR（faster-whisper small），**可能有错别字**。", ""]
        for s in segs:
            L.append(f"- `{mmss(s['start'])}` {s['text']}")
    else:
        L += ["> 没有识别到人声。"]
    L += ["", "返回 [[_索引]]", ""]
    text = "\n".join(L)
    try:
        from opencc import OpenCC
        text = OpenCC("t2s").convert(text)
    except Exception:
        pass
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    # 清理临时音频
    for f in (m4s, os.path.join(WORK, bv + ".wav")):
        try:
            os.remove(f)
        except Exception:
            pass
    return "ok", title, len(segs)


def worker(mid, shard, outdir, force, widx, logpath):
    def log(m):
        with open(logpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"w": widx, "msg": m, "ts": time.strftime("%H:%M:%S")}, ensure_ascii=False) + "\n")

    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    with httpx.Client(headers=H, follow_redirects=True, timeout=300, trust_env=False) as c:
        for i, v in enumerate(shard, 1):
            try:
                st, title, n = one_video(c, model, v["bvid"], outdir, force, log)
                log(f"{i}/{len(shard)} {st} {v['bvid']} segs={n} {title[:40]}")
            except Exception as e:
                log(f"{i}/{len(shard)} FAIL {v['bvid']} {type(e).__name__}: {e}")
            time.sleep(0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mid", type=int, required=True)
    ap.add_argument("--outdir", default="")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存清单重新枚举")
    ap.add_argument("--list-tries", type=int, default=6)
    a = ap.parse_args()
    logpath = os.path.join(WORK, f"bili_up_{a.mid}.jsonl")

    def log(m):
        line = f"[{time.strftime('%H:%M:%S')}] {m}"
        print(line, flush=True)
        with open(logpath, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"msg": m, "ts": time.strftime("%H:%M:%S")}, ensure_ascii=False) + "\n")

    manifest = os.path.join(WORK, f"bili_up_{a.mid}_manifest.json")
    cached = []
    if os.path.exists(manifest) and not a.refresh:
        try:
            cached = json.load(open(manifest, encoding="utf-8"))
        except Exception:
            cached = []
    if cached:
        vids = cached
        name = str(a.mid)
        try:
            with httpx.Client(headers=H, follow_redirects=True, timeout=30, trust_env=False) as cc:
                card = getjson(cc, "https://api.bilibili.com/x/web-interface/card", {"mid": a.mid})
                name = ((card.get("data") or {}).get("card") or {}).get("name") or name
        except Exception:
            pass
        log(f"用缓存清单：{len(vids)} 条")
    else:
        with httpx.Client(headers=H, follow_redirects=True, timeout=60, trust_env=False) as c:
            card = getjson(c, "https://api.bilibili.com/x/web-interface/card", {"mid": a.mid})
            name = ((card.get("data") or {}).get("card") or {}).get("name") or str(a.mid)
            vids = list_all(c, a.mid, log, name, a.list_tries)
    if not vids:
        log("没有拿到视频列表"); return 1
    if a.limit:
        vids = vids[: a.limit]
    outdir = os.path.join(VAULT, "AI工具精选", "视频", a.outdir or name)
    os.makedirs(outdir, exist_ok=True)
    manifest = os.path.join(WORK, f"bili_up_{a.mid}_manifest.json")
    json.dump(vids, open(manifest, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"UP={name} 视频 {len(vids)} 条 → {outdir}")

    n = min(a.workers, max(1, len(vids)))
    shards = [vids[i::n] for i in range(n)]
    procs = [Process(target=worker, args=(a.mid, sh, outdir, a.force, i, logpath)) for i, sh in enumerate(shards) if sh]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    # 索引
    files = sorted(f for f in os.listdir(outdir) if f.endswith(".md") and not f.startswith("_"))
    idx = ["---", "类型: 索引", f"tags: [AI工具, {name}]", f"日期: {time.strftime('%Y-%m-%d')}", "---", "",
           f"# {name} · 视频全集（{len(files)} 条）", "",
           "| # | 标题 |", "| --- | --- |"]
    for i, f in enumerate(files, 1):
        idx.append(f"| {i} | [[{f[:-3]}]] |")
    idx += ["", "返回 [[_AI工具精选索引]]", ""]
    open(os.path.join(outdir, "_索引.md"), "w", encoding="utf-8", newline="\n").write("\n".join(idx))
    log(f"DONE 笔记 {len(files)} 条，索引已生成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
