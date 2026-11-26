#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成「环境与工具清单」仓库的内容：README + inventory/*.md + data/*.csv/json。"""
import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from datetime import date
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

VAULT = str(VAULT_DIR)
REPO = str(HOME / "env-audit-repo")
SKILLS = os.path.expanduser(r"~\.agents\skills")


def main():
    os.makedirs(os.path.join(REPO, "inventory"), exist_ok=True)
    os.makedirs(os.path.join(REPO, "data"), exist_ok=True)

    skills = json.load(open(str(LOGS_DIR / "skills_inventory.json"), encoding="utf-8"))

    # ---- inventory/skills.md
    L = ["# 本机技能清单（103 个）", "",
         f"采集时间：{date.today().isoformat()}　｜　来源目录：`~/.agents/skills/`", "",
         "> 「首次入库」为目录 mtime，仅作时间参考，不代表原作者发布时间。", "",
         "| # | 技能 | 说明 | 文件数 | 入库 |", "| --- | --- | --- | --- | --- |"]
    for i, s in enumerate(skills, 1):
        desc = s["desc"].replace("|", "／")[:110]
        L.append(f"| {i} | `{s['name']}` | {desc} | {s['files']} | {s['mtime']} |")
    open(os.path.join(REPO, "inventory", "skills.md"), "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")

    # ---- data/skills.csv
    with open(os.path.join(REPO, "data", "skills.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "description", "files", "mtime"])
        for s in skills:
            w.writerow([s["name"], s["desc"], s["files"], s["mtime"]])

    # ---- 插件
    plugdir = os.path.join(VAULT, ".obsidian", "plugins")
    plugins = []
    if os.path.isdir(plugdir):
        for d in sorted(os.listdir(plugdir)):
            m = os.path.join(plugdir, d, "manifest.json")
            if os.path.exists(m):
                j = json.load(open(m, encoding="utf-8"))
                plugins.append({"id": j.get("id"), "name": j.get("name"),
                                "version": j.get("version"), "desc": j.get("description", "")})
    L = ["# Obsidian 插件清单", "",
         f"落点：`{VAULT}\\.obsidian\\plugins\\`", "",
         "| 插件 | 名称 | 版本 | 作用 |", "| --- | --- | --- | --- |"]
    for p in plugins:
        L.append(f"| `{p['id']}` | {p['name']} | {p['version']} | {p['desc'].replace('|','／')} |")
    open(os.path.join(REPO, "inventory", "plugins.md"), "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")

    # ---- 脚本
    scripts = []
    for p in sorted(os.listdir(str(HOME))):
        fp = os.path.join(str(HOME), p)
        if not os.path.isfile(fp):
            continue
        if os.path.splitext(p)[1].lower() not in (".py", ".ps1", ".cmd", ".mjs"):
            continue
        desc = ""
        try:
            t = open(fp, encoding="utf-8", errors="replace").read(1200)
            m = re.search(r'"""(.{0,120}?)\n', t) or re.search(r"\.SYNOPSIS\s*\n(.{0,120})", t)
            desc = m.group(1).strip().replace("\n", " ") if m else ""
        except Exception:
            pass
        scripts.append({"file": p, "kb": round(os.path.getsize(fp) / 1024, 1), "desc": desc})
    L = ["# 自建脚本清单", "", f"落点：`C:\\bili-index\\`（{len(scripts)} 个）", "",
         "| 文件 | KB | 用途 |", "| --- | --- | --- |"]
    for s in scripts:
        L.append(f"| `{s['file']}` | {s['kb']} | {s['desc'].replace('|','／')[:100]} |")
    open(os.path.join(REPO, "inventory", "scripts.md"), "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    with open(os.path.join(REPO, "data", "scripts.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "kb", "description"])
        for s in scripts:
            w.writerow([s["file"], s["kb"], s["desc"]])

    # ---- UP 笔记统计
    up = Counter()
    for dp, dns, fns in os.walk(VAULT):
        if any(x in dp for x in (".git", ".obsidian", ".echoink")):
            continue
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            try:
                head = open(os.path.join(dp, fn), encoding="utf-8", errors="replace").read(1200)
            except Exception:
                continue
            m = re.search(r"(?m)^UP:\s*(.+)$", head)
            if m:
                up[m.group(1).strip()] += 1
    L = ["# 视频/课程笔记来源", "", f"带 `UP:` 字段的笔记共 **{sum(up.values())}** 篇，涉及 **{len(up)}** 个来源。", "",
         "| 来源 | 笔记数 |", "| --- | --- |"]
    for name, c in up.most_common():
        L.append(f"| {name} | {c} |")
    open(os.path.join(REPO, "inventory", "sources.md"), "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    with open(os.path.join(REPO, "data", "sources.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "notes"])
        for name, c in up.most_common():
            w.writerow([name, c])

    # ---- README
    readme = f"""# 环境与工具清单（DSH × Obsidian）

本仓库是 2026-11-26 对一台 Windows 机器上「知识库 + 智能体工具链」的**只读快照式盘点**，
用于核查「装了什么、从哪来、落在哪」。

## 目录

| 文件 | 内容 |
| --- | --- |
| [`inventory/plugins.md`](inventory/plugins.md) | Obsidian 社区插件（{len(plugins)} 个，含版本与上游） |
| [`inventory/skills.md`](inventory/skills.md) | 本机技能（{len(skills)} 个，含说明与文件数） |
| [`inventory/scripts.md`](inventory/scripts.md) | 自建脚本（{len(scripts)} 个，按文件名与用途） |
| [`inventory/sources.md`](inventory/sources.md) | 视频/课程笔记来源统计（{len(up)} 个来源，{sum(up.values())} 篇） |
| [`data/*.csv`](data/) | 上述清单的机器可读版（UTF-8 BOM，Excel 可直接开） |

## 配套文档

原始盘点笔记在本地 Obsidian 库 `00_总览/安装清单（核查用）2026-11-26.md`，
包含「待确认的四处偏差」与一键自查命令。

## 边界

- 只记录**元数据**（名称、版本、文件数、路径），不包含任何笔记正文、密钥或个人数据；
- 技能说明取自各自 `SKILL.md` 的 `description` 字段，原样截断，未改写；
- 版本与数量为采集时快照，之后可能变化。

## 复现

```powershell
# 插件
Get-Content "<vault>\\.obsidian\\community-plugins.json"
# 技能
(Get-ChildItem $env:USERPROFILE\\.agents\\skills -Directory).Count
# 脚本
(Get-ChildItem C:\\bili-index -File | Where-Object Extension -in '.py','.ps1').Count
```

采集于 {date.today().isoformat()}。
"""
    open(os.path.join(REPO, "README.md"), "w", encoding="utf-8", newline="\n").write(readme)
    json.dump({"plugins": plugins, "skills": skills, "scripts": scripts,
               "sources": dict(up)}, open(os.path.join(REPO, "data", "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("repo built:", REPO, "plugins", len(plugins), "skills", len(skills), "scripts", len(scripts), "sources", len(up))


if __name__ == "__main__":
    main()
