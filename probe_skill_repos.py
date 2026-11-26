#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""浅探测 20 个 skill 仓库：只取文件清单 + README，判断「有真脚本 / 纯提示词 / 只是索引」。

直连 github 在本机必超时，统一走 gh-proxy.com 镜像；blob:none 只拉元数据。
输出：C:\\bili-index\\logs\\skill_probe\\probe.json + probe.tsv
"""
import json
import os
import subprocess
import time
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

WORK = str(SKILL_PROBE_DIR)
MIRROR = "https://gh-proxy.com/"
REPOS = [
    ("Yuan1z0825/nature-skills", "Nature 全流程"),
    ("ChenLiu-1996/figures4papers", "顶会配图脚本"),
    ("wubing2023/paperspine", "论文结构化拆解"),
    ("Haojae/scipilot-figure-skill", "顶刊级作图"),
    ("handsome-rich/Awesome-Auto-Research-Tools", "自动化研究工具汇总"),
    ("pengjunchi0/codex-visio-paper-figure-skill", "图转 Visio"),
    ("TingxiYu/academic-figure-skill", "数据→图表"),
    ("HuiyuLi-2000/Chinese-Grant-Writer-Skills", "国自然申请书"),
    ("Deepshare-Official/CCF-Figure", "CCF 配图"),
    ("Liuxiangjian-ai/reference-checker-skill", "参考文献核查"),
    ("fuyuxiang/patent-disclosure-skill", "专利交底书"),
    ("cuihuash/CiteVerify", "引文核查"),
    ("Schimasuperbra/distill-my-mentor", "导师蒸馏"),
    ("zhangzzk/arxiv-digest-skill", "arXiv 日报"),
    ("jonckr/cite-verify", "Crossref 引文核验"),
    ("WangJ226/Light", "27 技能包"),
    ("JasperPWang/lab-codex-skills", "综述框架"),
    ("GeederX/Paper_RAG_Skill", "多论文 RAG"),
    ("xxy985/literature-review-workflow", "文献综述工作流"),
    ("Elite-Lee/Supervisor-Skills", "博导经验"),
]
SCRIPT_EXT = (".py", ".js", ".ts", ".sh", ".ps1", ".r", ".m", ".ipynb", ".go", ".java")


def run(args, timeout=240):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def probe(owner_repo, dest):
    url = MIRROR + "https://github.com/" + owner_repo
    if not os.path.isdir(os.path.join(dest, ".git")):
        rc, out = run(["git", "clone", "--depth", "1", "--filter=blob:none",
                       "--no-checkout", url, dest])
        if rc != 0:
            return {"repo": owner_repo, "ok": False, "err": out.strip()[-200:]}
    rc, files = run(["git", "-C", dest, "ls-tree", "-r", "HEAD", "--name-only"])
    if rc != 0:
        return {"repo": owner_repo, "ok": False, "err": (files or "")[-200:]}
    names = [x for x in files.splitlines() if x.strip()]
    low = [n.lower() for n in names]
    n_script = sum(1 for n in low if n.endswith(SCRIPT_EXT))
    n_md = sum(1 for n in low if n.endswith(".md"))
    skill_md = any(os.path.basename(n).upper() == "SKILL.MD" for n in low)
    readme = next((n for n in names if os.path.basename(n).lower().startswith("readme")), None)
    head = ""
    if readme:
        rc, txt = run(["git", "-C", dest, "show", f"HEAD:{readme}"])
        if rc == 0:
            head = txt[:1500]
    if n_script >= 3:
        kind = "有可执行脚本"
    elif skill_md or n_md >= 3:
        kind = "提示词/技能包（SKILL.md）"
    else:
        kind = "文档/索引"
    return {"repo": owner_repo, "ok": True, "files": len(names), "scripts": n_script,
            "md": n_md, "has_skill_md": skill_md, "readme": readme,
            "kind": kind, "readme_head": head,
            "top": names[:25]}


def main():
    os.makedirs(WORK, exist_ok=True)
    out = []
    for i, (repo, desc) in enumerate(REPOS, 1):
        dest = os.path.join(WORK, repo.replace("/", "__"))
        t0 = time.time()
        rec = probe(repo, dest)
        rec["desc"] = desc
        rec["secs"] = round(time.time() - t0, 1)
        out.append(rec)
        print(f"[{i}/{len(REPOS)}] {repo}: {rec.get('kind', 'FAIL')} "
              f"scripts={rec.get('scripts', '-')} md={rec.get('md', '-')} "
              f"{rec['secs']}s {rec.get('err', '')[:60]}", flush=True)
    json.dump(out, open(os.path.join(WORK, "probe.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(os.path.join(WORK, "probe.tsv"), "w", encoding="utf-8") as fh:
        fh.write("repo\tdesc\tok\tfiles\tscripts\tmd\tskill_md\tkind\n")
        for r in out:
            fh.write("\t".join(str(r.get(k, "")) for k in
                               ("repo", "desc", "ok", "files", "scripts", "md", "has_skill_md", "kind")) + "\n")
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
