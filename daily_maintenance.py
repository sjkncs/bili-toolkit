#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每日刷新：建当日日记 + 用未完成任务刷新「今日任务（自动）」区块。

2026-11-07 重写。原脚本 `F:\\bili-index\\daily_maintenance.py` 随 F 盘掉盘丢失，
本版按 vault 里留下的产物反推行为：
  - 日记模板：`00_总览/模板/日记模板.md`（占位符 {{date:YYYY-MM-DD}} / {{date}}）
  - 任务来源：`30_任务/*.md` 的 frontmatter（状态 / 优先级 / 截止 / 项目）
  - 产出格式与历史日记一致：
        - [ ] [[任务名]] · 中 优先级 · 截止 2026-11-05 · 论文投稿

用法:
    python daily_maintenance.py [--vault PATH] [--date YYYY-MM-DD] [--dry-run]
"""
import argparse
import datetime as dt
import os
import re
import sys
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

DEF_VAULT = str(VAULT_DIR)
JOURNAL_DIR = "20_日记"
TASK_DIR = "30_任务"
TEMPLATE = os.path.join("00_总览", "模板", "日记模板.md")
MARK = "## 今日任务（自动）"
LOG_DIR = str(LOGS_DIR)


def read_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out = {}
    for line in block.splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def collect_tasks(vault):
    tdir = os.path.join(vault, TASK_DIR)
    tasks = []
    if not os.path.isdir(tdir):
        return tasks
    for dp, _, fns in os.walk(tdir):
        for fn in fns:
            if not fn.lower().endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            try:
                text = open(p, "r", encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            fm = read_frontmatter(text)
            status = fm.get("状态", "").strip()
            if not status or status in ("已完成", "完成", "done", "Done"):
                continue
            tasks.append({
                "name": os.path.splitext(fn)[0],
                "status": status,
                "prio": fm.get("优先级", "").strip(),
                "due": fm.get("截止", "").strip(),
                "proj": fm.get("项目", "").strip(),
            })
    tasks.sort(key=lambda t: (t["due"] or "9999-99-99", t["name"]))
    return tasks


def render_tasks(tasks):
    if not tasks:
        return ["- 暂无未完成任务。"]
    lines = []
    for t in tasks:
        parts = [f"[[{t['name']}]]"]
        if t["prio"]:
            parts.append(f"{t['prio']} 优先级")
        if t["due"]:
            parts.append(f"截止 {t['due']}")
        if t["proj"]:
            parts.append(t["proj"])
        lines.append("- [ ] " + " · ".join(parts))
    return lines


def replace_block(text, lines):
    """替换 MARK 到下一个 `## ` 之间的内容；没有该段就追加。"""
    idx = text.find(MARK)
    if idx == -1:
        return text.rstrip("\n") + f"\n\n{MARK}\n\n" + "\n".join(lines) + "\n"
    start = idx + len(MARK)
    nxt = text.find("\n## ", start)
    body = "\n\n" + "\n".join(lines) + "\n"
    if nxt == -1:
        return text[:start] + body
    return text[:start] + body + text[nxt:]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=DEF_VAULT)
    ap.add_argument("--date", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    vault = a.vault
    if not os.path.isdir(vault):
        print(f"[FAIL] vault 不存在: {vault}")
        return 2

    today = a.date or dt.date.today().isoformat()
    tasks = collect_tasks(vault)
    lines = render_tasks(tasks)

    jdir = os.path.join(vault, JOURNAL_DIR)
    os.makedirs(jdir, exist_ok=True)
    jpath = os.path.join(jdir, f"{today}.md")

    created = False
    if os.path.exists(jpath):
        text = open(jpath, "r", encoding="utf-8", errors="replace").read()
    else:
        tpl_path = os.path.join(vault, TEMPLATE)
        if os.path.exists(tpl_path):
            text = open(tpl_path, "r", encoding="utf-8", errors="replace").read()
        else:
            text = ("---\n类型: 日记\ntags: [日记]\n日期: \"{{date}}\"\n---\n\n"
                    "# {{date}} 日记\n\n## 今日任务（自动）\n")
        text = text.replace("{{date:YYYY-MM-DD}}", today).replace("{{date}}", today)
        created = True

    new = replace_block(text, lines)
    changed = created or (new != text)

    if a.dry_run:
        print(f"[dry-run] {jpath}  created={created} changed={changed}")
        print("\n".join(lines))
        return 0

    if changed:
        with open(jpath, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)

    os.makedirs(LOG_DIR, exist_ok=True)
    log = os.path.join(LOG_DIR, f"daily_maintenance_{today}.log")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} created={created} changed={changed} "
                 f"tasks={len(tasks)} journal={jpath}\n")

    print(f"journal  : {jpath} (created={created}, updated={changed})")
    print(f"tasks    : {len(tasks)}")
    for ln in lines:
        print("  " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
