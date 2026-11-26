# bili-toolkit

把 B 站视频批量转成 Obsidian 笔记、给中文扫描教材做 OCR 分章、给知识库做链接体检的一小组脚本。
从一台 Windows 机器的实际工作流里抽出来的，**路径全部参数化**，逻辑未改。

> 原始脚本在作者机器上由计划任务调用；本仓库是可移植版本，所有路径从 `paths.py` 读取（环境变量优先）。

## 工具一览

| 脚本 | 作用 | 依赖外部程序 |
| --- | --- | --- |
| `bili_pipeline.py` | **一条龙**：docx/链接 → 笔记（元数据 / 关键帧 / 热评 / 分块并行 ASR / 简繁转换 / 索引） | ffmpeg |
| `bili_up.py` | 某 UP 全集：枚举全部投稿 → 多进程转写 → 笔记 + 索引（断点续跑） | ffmpeg |
| `bili_note.py` | 单条视频 → 笔记；`--pause-ocr` 可在转写时暂停 OCR 任务让出 CPU | ffmpeg |
| `bili_long_asr.py` | 长视频（2h+）切块 + 多进程 ASR，合并成绝对时间戳 | ffmpeg |
| `bili_batch_notes.py` | 批量短视频，模型只加载一次 | ffmpeg |
| `note_from_asr.py` | 用已有的分块 ASR 结果补写笔记 | — |
| `check_links.py` | Obsidian 库链接体检：统计 `[[wikilink]]` 断链并输出 JSON | — |
| `daily_maintenance.py` | 每日日记生成 + 「今日任务（自动）」区块刷新（幂等） | — |
| `make_ocr_notes.py` | 扫描版教材：按页眉章号分章，合并行，写章节笔记并回写索引 | — |
| `ocr_slides.py` | 视频场景帧批量 OCR（rapidocr） | ffmpeg |
| `probe_skill_repos.py` | 浅探测一批 GitHub 仓库（blob:none），读文件树与 README | git |
| `figs_cn_global_sci.py` | SCI 风格配图示例（Arial / 色盲友好 / 600 dpi + PDF） | — |
| `harness_mcp.py` | 本地 MCP 服务器（stdio / JSON-RPC 2.0，纯标准库） | — |
| `build_env_audit_repo.py` | 采集插件/技能/脚本/来源清单，产出 Markdown + CSV | — |

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

外部程序：

- **ffmpeg**（`bili_*` 与 `ocr_slides` 需要，需在 PATH 中）
- **git**（`probe_skill_repos` 需要）

模型：`faster-whisper` 会在首次使用时下载，或指向本地目录（见下）。

## 配置

复制 `.env.example` 为 `.env` 并改路径，或用系统环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `BILI_INDEX_HOME` | `C:\bili-index` | 工具根目录（日志、模型、临时文件都在它下面） |
| `OBSIDIAN_VAULT` | `<HOME>\SONG的终极兵器` | Obsidian 库根目录 |
| `WHISPER_MODEL` | `<HOME>\models\faster-whisper-small` | faster-whisper 模型目录（CTranslate2 格式） |

`paths.py` 会把它们解析成 `HOME / VAULT_DIR / LOGS_DIR / BILI_LOGS_DIR / OCR_LOGS_DIR / WHISPER_MODEL`。

## 用法

```bash
# 从一份 docx（里面有 b23.tv 短链）批量做笔记
python bili_pipeline.py --docx "D:\list.docx" --workers 4

# 直接给链接
python bili_pipeline.py --links https://b23.tv/xxxx BV1xxxxxxxxx

# 某个 UP 的全部投稿（先小样本试）
python bili_up.py --mid 49683148 --limit 3 --workers 2
python bili_up.py --mid 49683148 --workers 4

# 长视频单独转写（切 10 分钟块，5 进程）
python bili_long_asr.py --bvid BV1xxxxxxxxx --chunk 600 --workers 5 --lang zh

# 链接体检（退出码非 0 表示有断链）
python check_links.py "D:\vault" --json out.json

# 扫描教材分章
python make_ocr_notes.py --book os
```

## 已知边界

- 面向 **Windows + 中文** 场景：PowerShell 写文件需显式 UTF-8，`multiprocessing` 需 `if __name__ == "__main__":` 保护（仓库内脚本已遵守）。
- B 站接口风控严格：主页列表接口在密集请求后会返回 412，`bili_up.py` 内置退避重试；必要时改用搜索接口或降低频率。
- ASR 是本地 CPU 推理，准确率受模型大小限制，**转写文本仅作检索线索**，引用需回看原视频。
- OCR 分章依赖书页页眉的章号；没有书签的书（如部分扫描版）章边界可能差 1–2 页。

## 许可

MIT，见 `LICENSE`。
