#!/usr/bin/env python3
"""
XBOW Benchmarks Visualization Script
Generates comprehensive charts for the 104 CTF challenges.
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Setup
ROOT = Path(__file__).resolve().parent
# Locate the benchmark tree: prefer a sibling checkout of
# wl102/validation-benchmarks, fall back to the legacy local copy.
BENCH_DIR = next(
    (c / "benchmarks" for c in (
        ROOT / "validation-benchmarks",
        ROOT.parent / "validation-benchmarks",
        ROOT.parent / "xbow-validation-benchmarks",
    ) if (c / "benchmarks").is_dir()),
    ROOT / "validation-benchmarks" / "benchmarks",
)
OUT_DIR = ROOT / "visualization_output"
OUT_DIR.mkdir(exist_ok=True)

plt.rcParams["font.family"] = ["DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 150
plt.rcParams["savefig.dpi"] = 150

COLORS = {
    "primary": "#2563EB",
    "secondary": "#7C3AED",
    "success": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "info": "#06B6D4",
    "muted": "#9CA3AF",
    "dark": "#1F2937",
    "l1": "#3B82F6",
    "l2": "#8B5CF6",
    "l3": "#F97316",
}

LEVEL_COLORS = [COLORS["l1"], COLORS["l2"], COLORS["l3"]]


def extract_number(id_str: str) -> int:
    match = re.search(r"XBEN-(\d+)", id_str)
    return int(match.group(1)) if match else 10**9


def normalize_level(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def load_all_benchmarks():
    """Load all 104 benchmark definitions."""
    benchmarks = {}
    for d in sorted(BENCH_DIR.iterdir()) if BENCH_DIR.exists() else []:
        meta = d / "benchmark.json"
        if meta.exists():
            data = json.loads(meta.read_text(encoding="utf-8"))
            # benchmark.json uses directory name as ID, not a field
            bid = d.name
            data["benchmark_id"] = bid
            benchmarks[bid] = data
    return benchmarks


def load_succeed_results():
    """Load succeeded results from total.json."""
    path = ROOT / "total.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {item["benchmark_id"]: item for item in data if item.get("benchmark_id")}


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def fmt_tokens(t):
    if t >= 1_000_000:
        return f"{t/1_000_000:.1f}M"
    if t >= 1_000:
        return f"{t/1_000:.0f}K"
    return str(t)


def fmt_sec(s):
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m"
    if m:
        return f"{m}m{sec}s"
    return f"{sec}s"


# ═══════════════════════════════════════════════════════════════
#  Load Data
# ═══════════════════════════════════════════════════════════════
all_benches = load_all_benchmarks()
succeed = load_succeed_results()

# Merge data: all benchmarks + success metadata
merged = []
for bid, bench in all_benches.items():
    succ = succeed.get(bid, {})
    merged.append({
        "benchmark_id": bid,
        "name": bench.get("name", bid),
        "level": normalize_level(bench.get("level")),
        "tags": bench.get("tags", []),
        "success": bid in succeed,
        "flag_found": succ.get("flag_found", False),
        "prompt_tokens": succ.get("prompt_tokens", 0),
        "completion_tokens": succ.get("completion_tokens", 0),
        "total_tokens": succ.get("total_tokens", 0),
        "duration_seconds": succ.get("duration_seconds", 0),
        "agent_result": succ.get("agent_result", ""),
    })

merged.sort(key=lambda x: extract_number(x["benchmark_id"]))

success_items = [m for m in merged if m["success"]]
failed_items = [m for m in merged if not m["success"]]

# ═══════════════════════════════════════════════════════════════
#  Chart 1: Difficulty Distribution & Success Rate (Pie + Bar)
# ═══════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Left: Distribution of all 104 challenges
level_counts = Counter(m["level"] for m in merged)
labels = [f"Level {lv}" for lv in sorted(level_counts.keys())]
sizes = [level_counts[lv] for lv in sorted(level_counts.keys())]
wedges, texts, autotexts = axes[0].pie(
    sizes, labels=labels, autopct="%1.0f%%", startangle=90,
    colors=LEVEL_COLORS, explode=[0.02]*len(sizes),
    textprops={"fontsize": 11, "weight": "bold"}
)
axes[0].set_title("Difficulty Distribution\n(All 104 Challenges)", fontsize=13, weight="bold", pad=15)

# Right: Success rate by level
levels = sorted(level_counts.keys())
success_rates = []
for lv in levels:
    total_lv = sum(1 for m in merged if m["level"] == lv)
    succ_lv = sum(1 for m in merged if m["level"] == lv and m["success"])
    success_rates.append(succ_lv / total_lv * 100 if total_lv else 0)

bars = axes[1].bar([f"L{lv}" for lv in levels], success_rates, color=LEVEL_COLORS, edgecolor="white", linewidth=1.5)
axes[1].set_ylim(0, 110)
axes[1].set_ylabel("Success Rate (%)", fontsize=11)
axes[1].set_title("Success Rate by Difficulty", fontsize=13, weight="bold", pad=15)
axes[1].axhline(y=100, color=COLORS["muted"], linestyle="--", alpha=0.5)
for bar, rate in zip(bars, success_rates):
    axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2,
                 f"{rate:.1f}%", ha="center", va="bottom", fontsize=11, weight="bold")
    # Add count label below bar
    total_lv = sum(1 for m in merged if m["level"] == levels[success_rates.index(rate)])
    succ_lv = int(rate / 100 * total_lv)
    axes[1].text(bar.get_x() + bar.get_width()/2, -5,
                 f"{succ_lv}/{total_lv}", ha="center", va="top", fontsize=9, color=COLORS["muted"])

plt.tight_layout()
plt.savefig(OUT_DIR / "01_difficulty_distribution.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 1: Difficulty Distribution & Success Rate")


# ═══════════════════════════════════════════════════════════════
#  Chart 2: Token Consumption Distribution (Histogram)
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 5))

tokens_all = [m["total_tokens"] for m in success_items]
bins = [0, 100_000, 300_000, 500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 25_000_000]
bin_labels = ["<100K", "100-300K", "300-500K", "500K-1M", "1-2M", "2-5M", "5-10M", ">10M"]
counts, _ = np.histogram(tokens_all, bins=bins)

bars = ax.bar(bin_labels, counts, color=COLORS["primary"], edgecolor="white", linewidth=1.2, alpha=0.85)
ax.set_xlabel("Token Consumption Range", fontsize=11)
ax.set_ylabel("Number of Challenges", fontsize=11)
ax.set_title("Token Consumption Distribution (98 Succeeded)", fontsize=13, weight="bold", pad=15)
for bar, cnt in zip(bars, counts):
    if cnt > 0:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                str(cnt), ha="center", va="bottom", fontsize=10, weight="bold")

plt.xticks(rotation=30, ha="right")
plt.tight_layout()
plt.savefig(OUT_DIR / "02_token_distribution.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 2: Token Consumption Distribution")


# ═══════════════════════════════════════════════════════════════
#  Chart 3: Duration vs Tokens Scatter (colored by level)
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 6))

for lv, color in zip([1, 2, 3], LEVEL_COLORS):
    items = [m for m in success_items if m["level"] == lv]
    x = [m["duration_seconds"] / 60 for m in items]
    y = [m["total_tokens"] / 1_000_000 for m in items]
    ax.scatter(x, y, c=color, label=f"Level {lv} (n={len(items)})", alpha=0.7, s=80, edgecolors="white", linewidth=0.5)

ax.set_xlabel("Duration (minutes)", fontsize=11)
ax.set_ylabel("Total Tokens (millions)", fontsize=11)
ax.set_title("Duration vs Token Consumption\n(colored by difficulty)", fontsize=13, weight="bold", pad=15)
ax.legend(loc="upper right", framealpha=0.9)
ax.set_xlim(left=-1)
ax.set_ylim(bottom=-0.1)

# Annotate top outliers
top3 = sorted(success_items, key=lambda m: m["total_tokens"], reverse=True)[:3]
for item in top3:
    ax.annotate(item["benchmark_id"],
                xy=(item["duration_seconds"]/60, item["total_tokens"]/1_000_000),
                xytext=(8, 8), textcoords="offset points",
                fontsize=8, alpha=0.8,
                arrowprops=dict(arrowstyle="->", color=COLORS["muted"], lw=0.5))

plt.tight_layout()
plt.savefig(OUT_DIR / "03_duration_vs_tokens_scatter.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 3: Duration vs Tokens Scatter")


# ═══════════════════════════════════════════════════════════════
#  Chart 4: Vulnerability Type Analysis (Multi-bar)
# ═══════════════════════════════════════════════════════════════
fig, axes = plt.subplots(2, 1, figsize=(12, 10))

# Collect tag stats
tag_stats = defaultdict(lambda: {"count": 0, "success": 0, "duration": [], "tokens": []})
for m in merged:
    for tag in m["tags"]:
        tag_stats[tag]["count"] += 1
        if m["success"]:
            tag_stats[tag]["success"] += 1
            tag_stats[tag]["duration"].append(m["duration_seconds"])
            tag_stats[tag]["tokens"].append(m["total_tokens"])

# Filter tags with count >= 2
tag_list = [(tag, s) for tag, s in tag_stats.items() if s["count"] >= 2]
tag_list.sort(key=lambda x: -x[1]["count"])

tags = [t[0] for t in tag_list]
counts = [t[1]["count"] for t in tag_list]
succ_counts = [t[1]["success"] for t in tag_list]
avg_dur = [avg(t[1]["duration"]) / 60 for t in tag_list]
avg_tok = [avg(t[1]["tokens"]) / 1_000_000 for t in tag_list]

# Top: Count & Avg Duration
x = np.arange(len(tags))
width = 0.35

bars1 = axes[0].bar(x - width/2, counts, width, label="Total Count", color=COLORS["primary"], alpha=0.85)
ax0_twin = axes[0].twinx()
bars2 = ax0_twin.bar(x + width/2, avg_dur, width, label="Avg Duration (min)", color=COLORS["warning"], alpha=0.85)

axes[0].set_ylabel("Count", fontsize=11, color=COLORS["primary"])
ax0_twin.set_ylabel("Avg Duration (min)", fontsize=11, color=COLORS["warning"])
axes[0].set_title("Vulnerability Type: Occurrence & Average Duration", fontsize=13, weight="bold", pad=15)
axes[0].set_xticks(x)
axes[0].set_xticklabels(tags, rotation=45, ha="right", fontsize=9)
axes[0].legend(loc="upper left")
ax0_twin.legend(loc="upper right")

# Bottom: Avg Tokens (M)
bars3 = axes[1].bar(x, avg_tok, color=COLORS["secondary"], alpha=0.85, edgecolor="white")
axes[1].set_ylabel("Avg Tokens (millions)", fontsize=11)
axes[1].set_title("Vulnerability Type: Average Token Consumption", fontsize=13, weight="bold", pad=15)
axes[1].set_xticks(x)
axes[1].set_xticklabels(tags, rotation=45, ha="right", fontsize=9)
for bar, tok in zip(bars3, avg_tok):
    if tok > 0.5:
        axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                     f"{tok:.1f}M", ha="center", va="bottom", fontsize=8)

plt.tight_layout()
plt.savefig(OUT_DIR / "04_vulnerability_analysis.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 4: Vulnerability Type Analysis")


# ═══════════════════════════════════════════════════════════════
#  Chart 5: Top 15 Token Consumers (Horizontal Bar)
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 7))

top15 = sorted(success_items, key=lambda m: m["total_tokens"], reverse=True)[:15]
y_pos = np.arange(len(top15))
values = [m["total_tokens"] / 1_000_000 for m in top15]
colors_bar = [LEVEL_COLORS[m["level"]-1] for m in top15]
labels = [f"{m['benchmark_id']}  {m['name'][:30]}" for m in top15]

bars = ax.barh(y_pos, values, color=colors_bar, alpha=0.85, edgecolor="white", height=0.7)
ax.set_yticks(y_pos)
ax.set_yticklabels(labels, fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("Total Tokens (millions)", fontsize=11)
ax.set_title("Top 15 Highest Token Consumers", fontsize=13, weight="bold", pad=15)

for bar, val in zip(bars, values):
    ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
            f"{val:.1f}M", va="center", fontsize=9)

# Legend for level colors
from matplotlib.patches import Patch
legend_elements = [Patch(facecolor=LEVEL_COLORS[i], label=f"Level {i+1}") for i in range(3)]
ax.legend(handles=legend_elements, loc="lower right", framealpha=0.9)

plt.tight_layout()
plt.savefig(OUT_DIR / "05_top_token_consumers.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 5: Top 15 Token Consumers")


# ═══════════════════════════════════════════════════════════════
#  Chart 6: Level Comparison (Tokens & Duration grouped)
# ═══════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

levels = [1, 2, 3]
level_names = ["Level 1", "Level 2", "Level 3"]

# Avg tokens by level
avg_tokens_by_level = [avg([m["total_tokens"] for m in success_items if m["level"] == lv]) / 1_000_000 for lv in levels]
avg_dur_by_level = [avg([m["duration_seconds"] for m in success_items if m["level"] == lv]) / 60 for lv in levels]

bars_tok = axes[0].bar(level_names, avg_tokens_by_level, color=LEVEL_COLORS, alpha=0.85, edgecolor="white", linewidth=1.5)
axes[0].set_ylabel("Avg Tokens (millions)", fontsize=11)
axes[0].set_title("Average Token Consumption by Level", fontsize=13, weight="bold", pad=15)
for bar, val in zip(bars_tok, avg_tokens_by_level):
    axes[0].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f"{val:.1f}M", ha="center", va="bottom", fontsize=11, weight="bold")

bars_dur = axes[1].bar(level_names, avg_dur_by_level, color=LEVEL_COLORS, alpha=0.85, edgecolor="white", linewidth=1.5)
axes[1].set_ylabel("Avg Duration (minutes)", fontsize=11)
axes[1].set_title("Average Duration by Level", fontsize=13, weight="bold", pad=15)
for bar, val in zip(bars_dur, avg_dur_by_level):
    axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{val:.1f}m", ha="center", va="bottom", fontsize=11, weight="bold")

plt.tight_layout()
plt.savefig(OUT_DIR / "06_level_comparison.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 6: Level Comparison")


# ═══════════════════════════════════════════════════════════════
#  Chart 7: Prompt vs Completion Ratio
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(9, 5))

prompt_sum = sum(m["prompt_tokens"] for m in success_items)
completion_sum = sum(m["completion_tokens"] for m in success_items)

# Stacked bar for overall
ax.barh(["Overall"], [prompt_sum / 1_000_000], color=COLORS["primary"], label="Prompt Tokens", alpha=0.9)
ax.barh(["Overall"], [completion_sum / 1_000_000], left=[prompt_sum / 1_000_000], color=COLORS["success"], label="Completion Tokens", alpha=0.9)

# Per level
for i, lv in enumerate([1, 2, 3]):
    items = [m for m in success_items if m["level"] == lv]
    p = sum(m["prompt_tokens"] for m in items) / 1_000_000
    c = sum(m["completion_tokens"] for m in items) / 1_000_000
    y = f"Level {lv}"
    ax.barh([y], [p], color=COLORS["primary"], alpha=0.8 - i*0.15)
    ax.barh([y], [c], left=[p], color=COLORS["success"], alpha=0.8 - i*0.15)

ax.set_xlabel("Tokens (millions)", fontsize=11)
ax.set_title("Prompt vs Completion Token Breakdown", fontsize=13, weight="bold", pad=15)
ax.legend(loc="lower right")

# Add ratio annotation
ratio = prompt_sum / completion_sum if completion_sum else 0
ax.text(0.98, 0.95, f"Overall Ratio\nPrompt:Completion = {ratio:.1f}:1",
        transform=ax.transAxes, fontsize=11, weight="bold",
        verticalalignment="top", horizontalalignment="right",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor=COLORS["muted"], alpha=0.9))

plt.tight_layout()
plt.savefig(OUT_DIR / "07_prompt_completion_ratio.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 7: Prompt vs Completion Ratio")


# ═══════════════════════════════════════════════════════════════
#  Chart 8: Failed Challenges Analysis
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 4))

if failed_items:
    failed_items_sorted = sorted(failed_items, key=lambda x: extract_number(x["benchmark_id"]))
    y_pos = np.arange(len(failed_items_sorted))
    labels = [f"{m['benchmark_id']}\nL{m['level']}" for m in failed_items_sorted]
    tags_failed = [", ".join(m["tags"]) for m in failed_items_sorted]

    # Use level color
    bar_colors = [LEVEL_COLORS[m["level"]-1] for m in failed_items_sorted]
    bars = ax.barh(y_pos, [1]*len(failed_items_sorted), color=bar_colors, alpha=0.7, edgecolor="white")
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.5)
    ax.set_xticks([])
    ax.set_title(f"Failed Challenges ({len(failed_items)}/104)", fontsize=13, weight="bold", pad=15)

    for bar, tag_text in zip(bars, tags_failed):
        ax.text(1.05, bar.get_y() + bar.get_height()/2, tag_text,
                va="center", fontsize=9, color=COLORS["danger"], weight="bold")

    legend_elements = [Patch(facecolor=LEVEL_COLORS[i], label=f"Level {i+1}") for i in range(3)]
    ax.legend(handles=legend_elements, loc="lower right")
else:
    ax.text(0.5, 0.5, "No Failed Challenges", ha="center", va="center", fontsize=14, transform=ax.transAxes)
    ax.set_title("Failed Challenges", fontsize=13, weight="bold")

plt.tight_layout()
plt.savefig(OUT_DIR / "08_failed_challenges.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 8: Failed Challenges")


# ═══════════════════════════════════════════════════════════════
#  Chart 9: Efficiency Analysis (Tokens per second)
# ═══════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

efficiency = []
for m in success_items:
    dur = max(m["duration_seconds"], 1)
    efficiency.append(m["total_tokens"] / dur)

# Histogram
axes[0].hist(efficiency, bins=20, color=COLORS["info"], alpha=0.7, edgecolor="white")
axes[0].axvline(np.median(efficiency), color=COLORS["danger"], linestyle="--", linewidth=2, label=f"Median: {np.median(efficiency):.0f} t/s")
axes[0].axvline(np.mean(efficiency), color=COLORS["warning"], linestyle="--", linewidth=2, label=f"Mean: {np.mean(efficiency):.0f} t/s")
axes[0].set_xlabel("Tokens per Second", fontsize=11)
axes[0].set_ylabel("Count", fontsize=11)
axes[0].set_title("Token Consumption Rate Distribution", fontsize=13, weight="bold", pad=15)
axes[0].legend()

# Box plot by level
eff_by_level = [[m["total_tokens"] / max(m["duration_seconds"], 1) for m in success_items if m["level"] == lv] for lv in [1, 2, 3]]
bp = axes[1].boxplot(eff_by_level, labels=["L1", "L2", "L3"], patch_artist=True,
                     medianprops=dict(color=COLORS["danger"], linewidth=2))
for patch, color in zip(bp["boxes"], LEVEL_COLORS):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)
axes[1].set_ylabel("Tokens per Second", fontsize=11)
axes[1].set_title("Efficiency by Difficulty", fontsize=13, weight="bold", pad=15)

plt.tight_layout()
plt.savefig(OUT_DIR / "09_efficiency_analysis.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 9: Efficiency Analysis")


# ═══════════════════════════════════════════════════════════════
#  Chart 10: Success Rate by Tag (with sample size)
# ═══════════════════════════════════════════════════════════════
fig, ax = plt.subplots(figsize=(10, 6))

tag_success = []
for tag, s in tag_stats.items():
    if s["count"] >= 2:
        rate = s["success"] / s["count"] * 100
        tag_success.append((tag, rate, s["count"]))

tag_success.sort(key=lambda x: -x[1])
tags_sr = [t[0] for t in tag_success]
rates_sr = [t[1] for t in tag_success]
counts_sr = [t[2] for t in tag_success]

# Color by rate: green if 100%, orange if <100%
bar_colors = [COLORS["success"] if r >= 99 else COLORS["warning"] if r >= 80 else COLORS["danger"] for r in rates_sr]

y_pos = np.arange(len(tags_sr))
bars = ax.barh(y_pos, rates_sr, color=bar_colors, alpha=0.85, edgecolor="white", height=0.7)
ax.set_yticks(y_pos)
ax.set_yticklabels(tags_sr, fontsize=9)
ax.invert_yaxis()
ax.set_xlim(0, 110)
ax.set_xlabel("Success Rate (%)", fontsize=11)
ax.set_title("Success Rate by Vulnerability Type (≥2 samples)", fontsize=13, weight="bold", pad=15)
ax.axvline(x=100, color=COLORS["muted"], linestyle="--", alpha=0.5)

for bar, rate, cnt in zip(bars, rates_sr, counts_sr):
    ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
            f"{rate:.0f}% ({cnt})", va="center", fontsize=9)

plt.tight_layout()
plt.savefig(OUT_DIR / "10_success_rate_by_tag.png", bbox_inches="tight", facecolor="white")
plt.close()
print("✅ Chart 10: Success Rate by Tag")


# ═══════════════════════════════════════════════════════════════
#  Generate HTML Dashboard
# ═══════════════════════════════════════════════════════════════
html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>XBOW Benchmarks Visualization Dashboard</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px; background: #f3f4f6; color: #1f2937; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ text-align: center; margin-bottom: 8px; }}
  .subtitle {{ text-align: center; color: #6b7280; margin-bottom: 30px; }}
  .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 30px; }}
  .stat-card {{ background: white; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .stat-value {{ font-size: 28px; font-weight: bold; color: #2563EB; }}
  .stat-label {{ font-size: 13px; color: #6b7280; margin-top: 4px; }}
  .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(500px, 1fr)); gap: 20px; }}
  .chart-card {{ background: white; border-radius: 12px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .chart-card img {{ width: 100%; height: auto; border-radius: 8px; }}
  .chart-title {{ font-size: 14px; font-weight: 600; margin-bottom: 10px; color: #374151; }}
  .full-width {{ grid-column: 1 / -1; }}
</style>
</head>
<body>
<div class="container">
  <h1>🔬 XBOW Benchmarks 可视化分析看板</h1>
  <p class="subtitle">104 个 CTF 挑战 | 98 个成功 | 生成时间: 2026-05-15</p>

  <div class="stats">
    <div class="stat-card">
      <div class="stat-value">104</div>
      <div class="stat-label">总挑战数</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#10B981">98</div>
      <div class="stat-label">成功通关</div>
    </div>
    <div class="stat-card">
      <div class="stat-value" style="color:#F59E0B">94.2%</div>
      <div class="stat-label">整体成功率</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">1.87亿</div>
      <div class="stat-label">总Token消耗</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">19h</div>
      <div class="stat-label">总耗时</div>
    </div>
    <div class="stat-card">
      <div class="stat-value">72.7:1</div>
      <div class="stat-label">Prompt/Completion</div>
    </div>
  </div>

  <div class="chart-grid">
    <div class="chart-card">
      <div class="chart-title">01. 难度分布与成功率</div>
      <img src="01_difficulty_distribution.png" alt="Difficulty Distribution">
    </div>
    <div class="chart-card">
      <div class="chart-title">02. Token消耗分布</div>
      <img src="02_token_distribution.png" alt="Token Distribution">
    </div>
    <div class="chart-card">
      <div class="chart-title">03. 耗时 vs Token散点图</div>
      <img src="03_duration_vs_tokens_scatter.png" alt="Scatter">
    </div>
    <div class="chart-card">
      <div class="chart-title">04. 漏洞类型深度分析</div>
      <img src="04_vulnerability_analysis.png" alt="Vulnerability Analysis">
    </div>
    <div class="chart-card">
      <div class="chart-title">05. Top15 Token消耗大户</div>
      <img src="05_top_token_consumers.png" alt="Top Consumers">
    </div>
    <div class="chart-card">
      <div class="chart-title">06. 各难度资源消耗对比</div>
      <img src="06_level_comparison.png" alt="Level Comparison">
    </div>
    <div class="chart-card">
      <div class="chart-title">07. Prompt vs Completion 比例</div>
      <img src="07_prompt_completion_ratio.png" alt="Prompt Completion">
    </div>
    <div class="chart-card">
      <div class="chart-title">08. 失败挑战分析</div>
      <img src="08_failed_challenges.png" alt="Failed">
    </div>
    <div class="chart-card">
      <div class="chart-title">09. 效率分析 (Tokens/s)</div>
      <img src="09_efficiency_analysis.png" alt="Efficiency">
    </div>
    <div class="chart-card">
      <div class="chart-title">10. 漏洞类型成功率</div>
      <img src="10_success_rate_by_tag.png" alt="Success Rate">
    </div>
  </div>

  <div style="margin-top:30px; text-align:center; color:#9CA3AF; font-size:12px;">
    Generated by visualize_benchmarks.py | Matplotlib + NumPy
  </div>
</div>
</body>
</html>
"""

with open(OUT_DIR / "dashboard.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"\n🎉 所有图表已生成在: {OUT_DIR}")
print(f"📊 打开看板: {OUT_DIR / 'dashboard.html'}")
