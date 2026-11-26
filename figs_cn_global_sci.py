#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""SCI 风格配图（Arial / 无边框 / 色盲友好 / 600 dpi）：中国全球化战略 4 图。"""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
from matplotlib.lines import Line2D
from paths import (HOME, VAULT_DIR, LOGS_DIR, BILI_LOGS_DIR, OCR_LOGS_DIR,
                  WHISPER_MODEL, SKILL_PROBE_DIR)

plt.rcParams.update({
    "font.family": ["Arial", "Microsoft YaHei", "DejaVu Sans"],
    "font.size": 7.5,
    "axes.linewidth": 0.6,
    "axes.edgecolor": "#4D4D4D",
    "xtick.major.width": 0.6,
    "ytick.major.width": 0.6,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.frameon": False,
    "savefig.dpi": 600,
    "figure.dpi": 150,
    "axes.unicode_minus": False,
})

BLUE, VERM, GREEN, PURPLE = "#0072B2", "#D55E00", "#009E73", "#CC79A7"
GREY, LGREY, INK = "#4D4D4D", "#B9B9B9", "#1A1A1A"
OUT = str(VAULT_DIR / "90_附件" / "图" / "中国全球化战略" / "sci")
os.makedirs(OUT, exist_ok=True)
MM = 1 / 25.4


def panel(ax, label, x=-0.02, y=1.04):
    ax.text(x, y, label, transform=ax.transAxes, fontsize=9, fontweight="bold",
            va="bottom", ha="left", color=INK)


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), bbox_inches="tight",
                    facecolor="white")
    plt.close(fig)
    print("saved", name)


# (a) 阶段演化：四段带状路线图
def fig_stages():
    fig, ax = plt.subplots(figsize=(180 * MM, 52 * MM))
    stages = [
        ("1978–2000", "要素开放", "特区 · 外资\n土地与劳动力", GREY),
        ("2001–2012", "规则接轨", "加入 WTO\n嵌入全球价值链", BLUE),
        ("2013–2019", "主动布局", "一带一路\n自贸试验区", VERM),
        ("2020– 今", "规则塑造", "RCEP · CPTPP\n双循环", GREEN),
    ]
    for i, (yr, name, sub, c) in enumerate(stages):
        ax.add_patch(FancyBboxPatch((i + 0.06, 0.42), 0.88, 0.42,
                                    boxstyle="round,pad=0.0,rounding_size=0.04",
                                    fc=c, ec="none", alpha=0.95))
        ax.text(i + 0.5, 0.78, name, ha="center", va="center", fontsize=8,
                color="white", fontweight="bold")
        ax.text(i + 0.5, 0.53, yr, ha="center", va="center", fontsize=6.4, color="white")
        ax.text(i + 0.5, 0.30, sub, ha="center", va="top", fontsize=6.3, color=GREY, linespacing=1.35)
        if i < 3:
            ax.annotate("", xy=(i + 1.02, 0.63), xytext=(i + 0.94, 0.63),
                        arrowprops=dict(arrowstyle="-|>", color="#8C8C8C", lw=0.8))
    ax.set_xlim(0, 4)
    ax.set_ylim(-0.15, 1.0)
    ax.axis("off")
    panel(ax, "a", x=0.0, y=0.98)
    save(fig, "fig1_stages")

# (b) 五通框架：横条 + 五列卡片
def fig_five_links():
    fig, ax = plt.subplots(figsize=(180 * MM, 58 * MM))
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 2.0)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.05, 1.42), 4.9, 0.42,
                                boxstyle="round,pad=0.0,rounding_size=0.05",
                                fc=INK, ec="none"))
    ax.text(2.5, 1.63, "一带一路：共商、共建、共享", ha="center", va="center",
            fontsize=8, color="white", fontweight="bold")
    items = [
        ("政策沟通", "战略对接\n合作文件", BLUE),
        ("设施联通", "铁路·港口\n班列", VERM),
        ("贸易畅通", "通关便利\n跨境电商", GREEN),
        ("资金融通", "亚投行\n丝路基金", PURPLE),
        ("民心相通", "教育·文旅\n民生工程", "#6B6B6B"),
    ]
    for i, (nm, sub, c) in enumerate(items):
        x = 0.1 + i * 0.96
        ax.add_patch(FancyBboxPatch((x, 0.42), 0.86, 0.86,
                                    boxstyle="round,pad=0.0,rounding_size=0.05",
                                    fc="white", ec=c, lw=1.0))
        ax.add_patch(FancyBboxPatch((x, 0.42), 0.86, 0.12,
                                    boxstyle="square,pad=0.0", fc=c, ec="none"))
        ax.text(x + 0.43, 0.94, nm, ha="center", va="center", fontsize=7,
                color=INK, fontweight="bold")
        ax.text(x + 0.43, 0.70, sub, ha="center", va="center", fontsize=6.0,
                color=GREY, linespacing=1.35)
        ax.plot([x + 0.43, x + 0.43], [1.22, 1.42], "-", color=LGREY, lw=0.7)
    ax.text(0.05, 0.12, "五通框架；每列下方为实现该方向的代表性抓手。", fontsize=6.0, color=GREY)
    panel(ax, "b", x=0.0, y=1.0)
    save(fig, "fig2_five_links")

# (c) 四层结构：堆叠条（宽度递减）
def fig_layers():
    fig, ax = plt.subplots(figsize=(170 * MM, 78 * MM))
    rows = [
        ("规则层", "RCEP · CPTPP · DEPA", 4, BLUE),
        ("制度层", "22 个自贸试验区 · 海南自贸港", 3, GREEN),
        ("平台层", "综保区 · 跨境电商综试区", 2, VERM),
        ("通道层", "中欧班列 · 陆海新通道", 1, PURPLE),
    ]
    for i, (name, sub, w, c) in enumerate(rows):
        y = 3 - i
        ax.barh([y], [w], height=0.68, color=c, edgecolor="none", alpha=0.95)
        ax.text(0.12, y + 0.06, name, va="center", ha="left", fontsize=8,
                color="white", fontweight="bold")
        ax.text(0.12, y - 0.2, sub, va="center", ha="left", fontsize=6.6, color="white")
    ax.set_xlim(0, 4.5)
    ax.set_ylim(-0.6, 3.7)
    ax.set_yticks([])
    ax.set_xlabel("制度约束强度（示意，越宽越接近规则制定）", fontsize=7, color=GREY)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="x", colors=GREY)
    ax.set_xticks([1, 2, 3, 4])
    ax.set_xticklabels(["通道", "平台", "制度", "规则"])
    panel(ax, "c")
    save(fig, "fig3_layers")


# (d) 城市网络：两行节点 + 中枢带
def fig_city_network():
    fig, ax = plt.subplots(figsize=(170 * MM, 66 * MM))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 5.2)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((4.35, 1.05), 1.3, 3.1,
                                boxstyle="round,pad=0.06,rounding_size=0.12",
                                fc=INK, ec="none", zorder=3))
    ax.text(5.0, 2.95, "全球化\n战略", ha="center", va="center", color="white",
            fontsize=8, fontweight="bold", zorder=4, linespacing=1.4)
    ax.text(5.0, 1.62, "制度型\n开放", ha="center", va="center", color="#E6E6E6",
            fontsize=6.6, zorder=4, linespacing=1.4)

    top = [("北京", "总部·政治", 1.55), ("上海", "金融·航运", 3.15), ("广州", "商贸·会展", 8.05)]
    bot = [("成都/重庆", "陆港·班列", 1.55), ("西安", "丝路起点", 3.15),
           ("武汉/郑州", "中部枢纽", 7.75), ("深圳/香港", "科创·离岸", 9.45)]
    for nm, role, x in top:
        ax.plot([x], [4.25], "o", ms=7, mfc=BLUE, mec="white", mew=0.7, zorder=4)
        ax.text(x, 4.45, nm, ha="center", va="bottom", fontsize=6.8, color=INK, fontweight="bold")
        ax.text(x, 4.14, role, ha="center", va="top", fontsize=5.8, color=GREY)
        ax.plot([x, 4.62], [4.2, 3.6], "-", color=LGREY, lw=0.7, zorder=1)
    for nm, role, x in bot:
        ax.plot([x], [0.85], "o", ms=7, mfc=GREEN, mec="white", mew=0.7, zorder=4)
        ax.text(x, 1.06, nm, ha="center", va="bottom", fontsize=6.8, color=INK, fontweight="bold")
        ax.text(x, 0.74, role, ha="center", va="top", fontsize=5.8, color=GREY)
        ax.plot([x, 4.62], [0.9, 1.6], "-", color=LGREY, lw=0.7, zorder=1)
    ax.text(0.1, 4.72, "沿海枢纽", fontsize=6.8, color=BLUE, fontweight="bold")
    ax.text(0.1, 0.12, "内陆枢纽", fontsize=6.8, color=GREEN, fontweight="bold")
    panel(ax, "d", x=0.0, y=1.02)
    save(fig, "fig4_city_network")

if __name__ == "__main__":
    fig_stages()
    fig_five_links()
    fig_layers()
    fig_city_network()
