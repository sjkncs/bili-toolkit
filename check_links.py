#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Obsidian vault 链接体检。

用法:
    python C:\\bili-index\\check_links.py [vault_path] [--json out.json]

检查范围:
  1. [[wikilink]] / ![[embed]]       —— 目标笔记或附件是否存在
  2. [text](relative.md) / ![](img)  —— 相对路径链接是否存在
  3. 附件引用（png/jpg/svg/pdf/...）—— 是否真实落盘

判定规则（按 Obsidian 的真实解析顺序）:
  a. 相对当前笔记目录
  b. 相对 vault 根目录
  c. 全库唯一 basename 匹配（Obsidian 的短链行为）
  d. 路径大小写不敏感兜底（Windows 文件系统本身不敏感）
"""
import os
import re
import sys
import json
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
MEDIA_EXT = IMG_EXT | {".pdf", ".mp3", ".mp4", ".webm", ".zip", ".docx", ".xlsx", ".pptx"}
SKIP_DIRS = {".git", ".obsidian", ".trash", "__pycache__", "node_modules", ".venv"}

WIKI = re.compile(r"!?\[\[([^\[\]]+?)\]\]")
MD_LINK = re.compile(r"!?\[[^\]]*\]\(([^()]+?)\)")
CODE_FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def iter_notes(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(".md"):
                yield os.path.join(dirpath, fn)


def build_index(root):
    """返回 (basename -> [abspath], relpath(lower) -> abspath)。"""
    by_base = {}
    by_rel = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ap = os.path.join(dirpath, fn)
            rel = os.path.relpath(ap, root).replace("\\", "/")
            by_rel[rel.lower()] = ap
            by_base.setdefault(fn.lower(), []).append(ap)
    return by_base, by_rel


def strip_noise(text):
    text = CODE_FENCE.sub("", text)
    return INLINE_CODE.sub("", text)


def resolve(target, note_path, root, by_base, by_rel):
    """把引用目标解析成绝对路径，失败返回 None。"""
    t = target.strip().split("|")[0].split("#")[0].strip()
    if not t:
        return "EMPTY"  # [[#heading]] 这种同篇内跳转
    t = t.replace("\\", "/")
    if re.match(r"^[a-zA-Z]+://", t) or t.startswith("mailto:"):
        return "EXTERNAL"

    cands = []
    base_dir = os.path.dirname(note_path)
    cands.append(os.path.normpath(os.path.join(base_dir, t)))
    cands.append(os.path.normpath(os.path.join(root, t)))
    if not os.path.splitext(t)[1]:
        for ext in ("", ".md"):
            for c in list(cands):
                cands.append(c + ext)
    for c in cands:
        if os.path.exists(c):
            return c
    # basename 兜底
    name = os.path.basename(t)
    if name:
        hits = by_base.get(name.lower())
        if hits:
            return hits[0] if len(hits) == 1 else hits[0]
        for ext in (".md",):
            hits = by_base.get((name + ext).lower())
            if hits:
                return hits[0]
    rel = t.lstrip("./").lower()
    if rel in by_rel:
        return by_rel[rel]
    return None


def check(root):
    by_base, by_rel = build_index(root)
    notes = list(iter_notes(root))
    broken = []
    total_refs = 0
    for note in notes:
        try:
            text = open(note, "r", encoding="utf-8", errors="replace").read()
        except OSError as e:
            broken.append({"note": note, "ref": None, "kind": "read", "reason": f"read-error: {e}"})
            continue
        body = strip_noise(text)
        refs = [(m.group(0), m.group(1), "wiki") for m in WIKI.finditer(body)]
        refs += [(m.group(0), m.group(1), "md") for m in MD_LINK.finditer(body)]
        for raw, target, kind in refs:
            if raw.startswith("!") and not target.strip():
                continue
            total_refs += 1
            if kind == "md" and re.match(r"^[a-zA-Z]+://", target.strip()):
                continue
            res = resolve(target, note, root, by_base, by_rel)
            if res in ("EXTERNAL", "EMPTY"):
                continue
            if res is None:
                broken.append({
                    "note": os.path.relpath(note, root).replace("\\", "/"),
                    "ref": raw[:160],
                    "target": target.strip()[:160],
                    "kind": kind,
                    "embed": raw.startswith("!"),
                })
    wiki_broken = [b for b in broken if b.get("kind") == "wiki"]
    md_broken = [b for b in broken if b.get("kind") == "md"]
    return {
        "vault": root,
        "notes": len(notes),
        "refs": total_refs,
        "broken": len(broken),
        "broken_wiki": len(wiki_broken),
        "broken_md": len(md_broken),
        "items": broken,
    }


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    vault = argv[1] if len(argv) > 1 and not argv[1].startswith("-") else str(VAULT_DIR)
    strict = "--strict" in argv
    json_out = None
    if "--json" in argv:
        json_out = argv[argv.index("--json") + 1]
    if not os.path.isdir(vault):
        print(f"[FAIL] vault 不存在: {vault}")
        return 2
    r = check(vault)
    print(f"vault       : {r['vault']}")
    print(f"notes       : {r['notes']}")
    print(f"refs        : {r['refs']}")
    print(f"broken      : {r['broken']}  ([[wikilink]] {r['broken_wiki']} / [](md) {r['broken_md']})")
    for b in r["items"][:50]:
        if b.get("ref") is None:
            print(f"  ! {b['note']}  {b.get('reason')}")
        else:
            tag = "wiki" if b.get("kind") == "wiki" else "md  "
            print(f"  ! [{tag}] {b['note']}  ->  {b['target']}")
    if len(r["items"]) > 50:
        print(f"  ... 另有 {len(r['items']) - 50} 条")
    if json_out:
        os.makedirs(os.path.dirname(json_out), exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(r, fh, ensure_ascii=False, indent=2)
        print(f"json        : {json_out}")
    if strict:
        return 0 if r["broken"] == 0 else 1
    return 0 if r["broken_wiki"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
