#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 OCR 结果按章拆成逐页笔记。

输入：logs/ocr/<book>.json（页码 -> 该页 OCR 文本）
输出：10_科研/408 教材笔记/<书名> · 第N章 ….md，并在索引页里挂链接。

原则：只做「结构化 + 去噪」，不改写原文；OCR 错字保留，文首注明。
"""
import argparse
import json
import os
import re
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

V = str(VAULT_DIR)
NOTE_DIR = os.path.join(V, "10_科研", "408 教材笔记")
OCR_DIR = str(OCR_LOGS_DIR)

BOOKS = {
    "os": dict(name="王道 2027 操作系统", pdf="王道2027操作系统-高清带书签.pdf"),
    "ds": dict(name="王道 2027 数据结构", pdf="2027数据结构_高清带书签版.pdf"),
    "cn": dict(name="王道 2027 计算机网络", pdf="2027计算机网络_高清带书签版.pdf"),
    "co": dict(name="王道 2027 计算机组成原理", pdf="2027计算机组成原理_高清带书签版.pdf"),
}

CH_RE = re.compile(r"^\s*第\s*([一二三四五六七八九十0-9]{1,3})\s*章\s*(.*)$")
NOISE = re.compile(r"^[\s·•\.\-—_=~]+$")


def clean_lines(text):
    out = []
    for l in (text or "").splitlines():
        s = l.strip()
        if not s or NOISE.match(s):
            continue
        if re.fullmatch(r"\d{1,3}", s):          # 页码
            continue
        cjk = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", s))
        if cjk < 2:                               # 纯符号行
            continue
        if cjk / max(1, len(s)) < 0.5:            # 符号占比过高（OCR 噪声）
            continue
        out.append(s)
    ded = []
    for s in out:
        if ded and ded[-1] == s:
            continue
        ded.append(s)

    # 合并被 PDF 折行截断的句子：上一行没有句末标点，且当前行不像新条目
    merged = []
    for s in ded:
        is_bullet = bool(re.match(r"^([0-9]+[.、]|[①②③④⑤⑥⑦⑧⑨⑩]|第[一二三四五六七八九十]+[章节]|[（(]\d|[-·•])", s))
        prev_end = bool(merged) and bool(re.search(r"[。；：！？!?：:]$", merged[-1]))
        if merged and not is_bullet and not prev_end and len(merged[-1]) > 20 and len(s) < 60:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return merged


def load_pages(book):
    p = os.path.join(OCR_DIR, f"{book}.json")
    if not os.path.exists(p):
        # 兼容只有 part 文件的情况
        merged = {}
        for f in sorted(os.listdir(OCR_DIR)):
            if f.startswith(f"{book}.part") and f.endswith(".json"):
                try:
                    for k, v in json.load(open(os.path.join(OCR_DIR, f), encoding="utf-8")).items():
                        if v and (k not in merged or len(v) > len(merged[k])):
                            merged[k] = v
                except Exception:
                    pass
        return {int(k): v for k, v in merged.items()}
    raw = json.load(open(p, encoding="utf-8"))
    return {int(k): v for k, v in raw.items()}


def split_chapters(pages):
    """按「页眉里的章号」归组：连续同章号的页并成一章。

    扫描书每页页眉都印着「第N章 …」，不能把每个匹配都当成新章起点。
    """
    nums = sorted(pages)
    seq = []            # [(page, no, title)]
    for p in nums:
        lines = clean_lines(pages[p])
        no, title = None, ""
        # 前 12 页是封面/前言/目录，目录里也会出现「第N章 13」这类行，不能当章起点
        if p >= 13:
            for l in lines[:6]:
                m = CH_RE.match(l)
                if m and len(l) < 40:
                    no, title = m.group(1), (m.group(2) or "").strip()
                    break
        seq.append((p, no, title))

    chapters, cur = [], None
    last_no = "0"
    for p, no, title in seq:
        eff = no if no else last_no
        if cur is None or eff != cur["no"]:
            if cur:
                chapters.append(cur)
            cur = {"no": eff, "title": title, "start": p, "pages": [p]}
            if eff == "0":
                cur["title"] = "前置（前言/目录）"
        else:
            cur["pages"].append(p)
            if not cur["title"] and title:
                cur["title"] = title
        if no:
            last_no = no
    if cur:
        chapters.append(cur)

    # 合并过短的章（<8 页且起始页靠前，多为目录/前言误判）
    merged = []
    for c in chapters:
        if merged and len(c["pages"]) < 8 and c["start"] < 30:
            merged[-1]["pages"].extend(c["pages"])
        else:
            merged.append(c)
    return merged


SECTION_RE = re.compile(r"^\s*(\d{1,2}\.\d{1,2})\s*[、. ]\s*(\S.{1,40})$")


def find_sections(pages, page_list):
    """在一章里找 N.N 型小节标题，返回 [(页码, 节号, 标题)]。"""
    out = []
    for p in page_list:
        for l in clean_lines(pages.get(p))[:8]:
            m = SECTION_RE.match(l)
            if m and not l.startswith(("图", "表")):
                out.append((p, m.group(1), m.group(2).strip()[:40]))
    # 去重（同节多次出现取第一次）
    seen, ded = set(), []
    for p, no, t in out:
        if no in seen:
            continue
        seen.add(no)
        ded.append((p, no, t))
    return ded


def write_chapter(book_key, ch, pages):
    meta = BOOKS[book_key]
    no_cn = ch["no"]
    name = f"{meta['name']} · 第{no_cn}章" + (f" {ch['title']}" if ch["title"] else "")
    name = name.replace("/", "／").strip()
    start, end = min(ch["pages"]), max(ch["pages"])
    lines = ["---", "类型: 逐页笔记（OCR）", f"教材: {meta['name']}", f"章: 第{no_cn}章",
             "tags: [408, 王道, 逐页笔记, OCR]", "日期: 2026-11-08",
             f"页码: P{start}–P{end}", f"来源: {meta['pdf']}", "---", "",
             f"# {name}", "",
             f"> 源文件：[[{meta['pdf']}#page={start}]]（P{start}–P{end}，共 {len(ch['pages'])} 页）",
             "> 正文为**扫描件 OCR** 原文（rapidocr，CPU），**可能有错字/串行**；"
             "需要精确引用时请对照 PDF 原页。", ""]
    secs = [s for s in find_sections(pages, ch["pages"]) if not s[2][:1].isdigit()]
    if len(secs) >= 3:
        lines += ["## 本章小节", "", "| 节 | 标题 | 页 |", "| --- | --- | --- |"]
        for p, no, t in secs:
            lines.append(f"| {no} | {t} | [[{meta['pdf']}#page={p}\\|P{p}]] |")
        lines.append("")
    for p in ch["pages"]:
        ls = clean_lines(pages.get(p))
        if not ls:
            lines += [f"## P{p:03d}", "", "- （该页无可识别文字）", ""]
            continue
        lines += [f"## P{p:03d}", ""]
        for s in ls[:24]:
            lines.append(f"- {s[:220]}")
        lines.append("")
    lines += ["返回索引：" + f"[[{meta['name']} 逐页笔记]]", ""]
    path = os.path.join(NOTE_DIR, name + ".md")
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
    return name, len(ch["pages"])


INDEX_NOTE = {
    "os": "王道 2027 操作系统 逐页笔记.md",
    "ds": "王道 2027 数据结构 逐页笔记.md",
    "cn": "王道 2027 计算机网络 逐页笔记.md",
    "co": "王道 2027 计算机组成原理 逐页笔记.md",
}
BEGIN = "<!-- OCR_CHAPTERS:BEGIN -->"
END = "<!-- OCR_CHAPTERS:END -->"


def update_index(book_key, made, pages):
    """把章节目录写回索引页（幂等：只替换 BEGIN..END 之间）。"""
    path = os.path.join(NOTE_DIR, INDEX_NOTE[book_key])
    if not os.path.exists(path):
        print("  (no index note, skip)")
        return
    rows = ["", BEGIN,
            "## 逐页正文（OCR）", "",
            f"> 全书 {len(pages)} 页已 OCR，按章拆成 {len(made)} 篇；"
            "正文是 OCR 原文，可能有错字，精确引用请对照 PDF。", "",
            "| 章 | 页数 | 笔记 |", "| --- | --- | --- |"]
    for name, cnt in made:
        rows.append(f"| {name.split('· ')[-1]} | {cnt} | [[{name}]] |")
    rows += ["", END, ""]
    block = "\n".join(rows)
    text = open(path, encoding="utf-8").read()
    if BEGIN in text and END in text:
        pre = text[: text.index(BEGIN)]
        post = text[text.index(END) + len(END):]
        text = pre + block + post
    else:
        text = text.rstrip("\n") + "\n" + block
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    print(f"  index updated: {INDEX_NOTE[book_key]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    a = ap.parse_args()
    pages = load_pages(a.book)
    if not pages:
        print("no ocr data for", a.book)
        return 1
    chs = split_chapters(pages)
    made = []
    for ch in chs:
        n, cnt = write_chapter(a.book, ch, pages)
        made.append((n, cnt))
        print(f"  wrote {n} ({cnt} 页)")
    print(f"{a.book}: {len(made)} 章，覆盖 P{min(pages)}–P{max(pages)}")
    update_index(a.book, made, pages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
