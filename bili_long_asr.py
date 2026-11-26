#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""长视频分块并行 ASR：把 2 小时的讲座切成 10 分钟片段，多进程转写再合并。

用法:
    python bili_long_asr.py --bvid BV1H2bo6uEFz --chunk 600 --workers 5 --lang en
输出:
    C:\\bili-index\\logs\\bili\\<bvid>.asr.json   {segments:[{start,end,text}]}
"""
import argparse
import glob
import json
import os
import subprocess
import time
from multiprocessing import Process
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

WORK = str(BILI_LOGS_DIR)
MODEL = str(WHISPER_MODEL)


def split(bvid, chunk, total=None):
    src = os.path.join(WORK, bvid + ".m4s")
    out_dir = os.path.join(WORK, bvid + "_chunks")
    os.makedirs(out_dir, exist_ok=True)
    if glob.glob(os.path.join(out_dir, "*.wav")):
        return out_dir
    subprocess.run(["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
                    "-f", "segment", "-segment_time", str(chunk),
                    os.path.join(out_dir, "chunk_%03d.wav")],
                   capture_output=True, check=True)
    return out_dir


def worker(files, lang, out_prefix, idx):
    from faster_whisper import WhisperModel
    m = WhisperModel(MODEL, device="cpu", compute_type="int8")
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        out = f"{out_prefix}.{base}.json"
        if os.path.exists(out):
            continue
        t0 = time.time()
        segs, info = m.transcribe(f, language=lang, vad_filter=True, beam_size=1,
                                  condition_on_previous_text=False)
        data = [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()}
                for s in segs if s.text.strip()]
        json.dump({"chunk": base, "lang": info.language, "segments": data},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"[w{idx}] {base} {time.time()-t0:.0f}s segs={len(data)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bvid", required=True)
    ap.add_argument("--chunk", type=int, default=600)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    d = split(a.bvid, a.chunk)
    files = sorted(glob.glob(os.path.join(d, "*.wav")))
    print(f"chunks={len(files)} workers={a.workers}", flush=True)
    out_prefix = os.path.join(WORK, a.bvid + ".part")
    buckets = [files[i::a.workers] for i in range(a.workers)]
    procs = [Process(target=worker, args=(b, a.lang, out_prefix, i))
             for i, b in enumerate(buckets) if b]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    merged = []
    for f in sorted(glob.glob(out_prefix + ".*.json")):
        rec = json.load(open(f, encoding="utf-8"))
        base = rec["chunk"]
        idx = int(base.split("_")[-1])
        off = idx * a.chunk
        for s in rec["segments"]:
            merged.append({"start": round(s["start"] + off, 1),
                           "end": round(s["end"] + off, 1), "text": s["text"]})
    merged.sort(key=lambda x: x["start"])
    out = os.path.join(WORK, a.bvid + ".asr.json")
    json.dump({"bvid": a.bvid, "segments": merged}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False)
    dur = merged[-1]["end"] if merged else 0
    print(f"merged {len(merged)} segments, ~{dur/60:.0f} min -> {out}", flush=True)


if __name__ == "__main__":
    main()
