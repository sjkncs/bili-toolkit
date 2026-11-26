#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""harness-tools —— EchoInk 用的本地 MCP 服务器（stdio / JSON-RPC 2.0，纯标准库）。

2026-11-07 重建：原版在 F:\\bili-index\\harness_mcp.py，随外置 SSD 掉盘丢失，
本版按 [[EchoInk 接入 Harness 工具（MCP）]] 记录的 6 个工具重写，并把根目录
默认值改成 C 盘布局。

路径限制：所有文件类工具只能访问 HARNESS_ROOTS 环境变量里的目录（分号分隔），
越界抛 PermissionError，调用方拿到 isError=true 而不是崩掉进程。

单独自测：
    echo {"jsonrpc":"2.0","id":1,"method":"tools/list"} | python harness_mcp.py
"""
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.request
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

SERVER_NAME = "harness-tools"
SERVER_VERSION = "1.1.0"
PROTOCOL_VERSION = "2024-11-05"

DEFAULT_ROOTS = r"%s;%s" % (VAULT_DIR, HOME)


def roots():
    raw = os.environ.get("HARNESS_ROOTS") or DEFAULT_ROOTS
    out = []
    for part in raw.split(";"):
        part = part.strip().strip('"')
        if part:
            out.append(os.path.realpath(part))
    return out


def resolve(path, must_exist=False):
    """把用户给的路径解析成绝对路径，并校验在允许的根目录内。"""
    if not path:
        raise PermissionError("path 不能为空")
    p = os.path.expanduser(str(path))
    if not os.path.isabs(p):
        p = os.path.join(roots()[0], p)
    real = os.path.realpath(p)
    for r in roots():
        if real == r or real.startswith(r + os.sep):
            if must_exist and not os.path.exists(real):
                raise FileNotFoundError(f"不存在: {real}")
            return real
    raise PermissionError(f"越界访问: {real}（允许的根: {roots()}）")


# ---------------------------------------------------------------- 工具实现

def tool_read_file(path, max_bytes=200_000, **_):
    real = resolve(path, must_exist=True)
    if os.path.isdir(real):
        raise IsADirectoryError(f"是目录不是文件: {real}")
    with open(real, "r", encoding="utf-8", errors="replace") as fh:
        data = fh.read(int(max_bytes) + 1)
    truncated = len(data) > int(max_bytes)
    if truncated:
        data = data[: int(max_bytes)]
    return data + ("\n…（已截断，超过 max_bytes）" if truncated else "")


def tool_write_file(path, content="", mode="overwrite", **_):
    real = resolve(path)
    os.makedirs(os.path.dirname(real), exist_ok=True)
    m = "a" if str(mode).lower() in ("append", "a") else "w"
    with open(real, m, encoding="utf-8", newline="\n") as fh:
        fh.write(content or "")
    return f"ok: {'追加' if m == 'a' else '写入'} {real}（{len(content or '')} 字符）"


def tool_list_dir(path=".", pattern="*", limit=200, **_):
    real = resolve(path or ".", must_exist=True)
    if not os.path.isdir(real):
        raise NotADirectoryError(f"不是目录: {real}")
    rows = []
    for name in sorted(os.listdir(real), key=lambda s: s.lower()):
        if pattern and pattern != "*" and not fnmatch.fnmatch(name.lower(), pattern.lower()):
            continue
        full = os.path.join(real, name)
        if os.path.isdir(full):
            rows.append(f"{name}/")
        else:
            try:
                rows.append(f"{name}\t{os.path.getsize(full)}")
            except OSError:
                rows.append(name)
        if len(rows) >= int(limit):
            rows.append(f"…（已达 limit={limit}）")
            break
    if not rows:
        return f"（空目录或无匹配: {real}，pattern={pattern}）"
    return f"{real}\n" + "\n".join(rows)


def tool_grep_files(pattern, glob="*.md", path=".", limit=80, **_):
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"正则不合法: {e}")
    base = resolve(path or ".", must_exist=True)
    hits, scanned = [], 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", "__pycache__")]
        for fn in filenames:
            if glob and not fnmatch.fnmatch(fn.lower(), glob.lower()):
                continue
            fp = os.path.join(dirpath, fn)
            scanned += 1
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    for no, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{os.path.relpath(fp, base)}:{no}:{line.rstrip()[:300]}")
                            if len(hits) >= int(limit):
                                return f"（命中 {limit} 条后截断，扫描 {scanned} 个文件）\n" + "\n".join(hits)
            except OSError:
                continue
    if not hits:
        return f"（无命中：pattern={pattern} glob={glob} 扫描 {scanned} 个文件）"
    return f"命中 {len(hits)} 条 / 扫描 {scanned} 个文件\n" + "\n".join(hits)


def tool_run_command(command, timeout=60, cwd=None, **_):
    if not command:
        raise ValueError("command 不能为空")
    workdir = resolve(cwd) if cwd else roots()[0]
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=workdir,
        capture_output=True,
        timeout=float(timeout),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    body = out or "（无 stdout）"
    if err:
        body += f"\n[stderr]\n{err[:4000]}"
    return f"exit={proc.returncode}\ncwd={workdir}\n{body[:20000]}"


def tool_http_get(url, max_chars=20_000, **_):
    if not re.match(r"^https?://", url or ""):
        raise ValueError("只支持 http/https")
    req = urllib.request.Request(url, headers={"User-Agent": "harness-tools/1.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read(2_000_000)
    text = raw.decode(charset, errors="replace")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    if len(text) > int(max_chars):
        text = text[: int(max_chars)] + "\n…（已截断）"
    return text


TOOLS = [
    {
        "name": "read_file",
        "description": "读文本文件（UTF-8），默认最多 200 KB。",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
            "required": ["path"],
        },
        "_fn": tool_read_file,
    },
    {
        "name": "write_file",
        "description": "写或追加文本文件，自动建目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"},
            },
            "required": ["path"],
        },
        "_fn": tool_write_file,
    },
    {
        "name": "list_dir",
        "description": "列目录（支持 glob），默认 200 项。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "pattern": {"type": "string", "default": "*"},
                "limit": {"type": "integer", "default": 200},
            },
        },
        "_fn": tool_list_dir,
    },
    {
        "name": "grep_files",
        "description": "正则搜文件，返回 文件:行:内容，默认 80 条。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string", "default": "*.md"},
                "path": {"type": "string", "default": "."},
                "limit": {"type": "integer", "default": 80},
            },
            "required": ["pattern"],
        },
        "_fn": tool_grep_files,
    },
    {
        "name": "run_command",
        "description": "执行 PowerShell 命令，默认 60 秒超时，cwd 默认第一个根目录。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "number", "default": 60},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        },
        "_fn": tool_run_command,
    },
    {
        "name": "http_get",
        "description": "抓网页正文（去标签），最多 2 万字符。",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 20000}},
            "required": ["url"],
        },
        "_fn": tool_http_get,
    },
]

TOOL_MAP = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------- JSON-RPC

def call_tool(name, args):
    spec = TOOL_MAP.get(name)
    if not spec:
        return {"content": [{"type": "text", "text": f"未知工具: {name}"}], "isError": True}
    try:
        text = spec["_fn"](**(args or {}))
        return {"content": [{"type": "text", "text": str(text)}], "isError": False}
    except Exception as e:  # noqa: BLE001 —— MCP 约定：工具错误回 isError，不炸服务
        return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "tools/list":
        result = {"tools": [{k: v for k, v in t.items() if k != "_fn"} for t in TOOLS]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        result = call_tool(params.get("name"), params.get("arguments") or {})
    elif method == "ping":
        result = {}
    elif method in ("notifications/initialized", "initialized", "shutdown"):
        return None
    elif method == "exit":
        raise SystemExit(0)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"未知方法: {method}"}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": f"JSON 解析失败: {e}"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = handle(msg)
        except SystemExit:
            break
        except Exception as e:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
