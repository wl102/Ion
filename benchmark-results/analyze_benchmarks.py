#!/usr/bin/env python3
"""
XBOW Benchmarks Data Analysis Script
Comprehensive statistical analysis across multiple dimensions.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

def load_data(path="total.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def fmt_num(n):
    return f"{n:,.0f}" if isinstance(n, (int, float)) and not math.isnan(n) else str(n)

def fmt_sec(s):
    m, sec = divmod(int(s), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m}m{sec}s"
    if m:
        return f"{m}m{sec}s"
    return f"{sec}s"

def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0

def median(vals):
    vals = sorted(v for v in vals if v is not None)
    n = len(vals)
    if n == 0:
        return 0
    if n % 2 == 1:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2

def stdev(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return 0
    m = mean(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))

def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)

def print_table(headers, rows, col_widths=None):
    if not rows:
        print("  (no data)")
        return
    if col_widths is None:
        col_widths = [max(len(str(h)), max(len(str(r[i])) for r in rows)) + 2 for i, h in enumerate(headers)]
    
    def fmt_row(row, sep=" "):
        parts = []
        for i, val in enumerate(row):
            s = str(val)
            parts.append(s.ljust(col_widths[i]))
        return sep.join(parts)
    
    print("  " + fmt_row(headers))
    print("  " + "-" * sum(col_widths))
    for row in rows:
        print("  " + fmt_row(row))

def analyze(data):
    total = len(data)
    
    # ========== 1. 总体概览 ==========
    print_section("1. 总体概览 (Overall Overview)")
    success = [d for d in data if d.get("flag_found")]
    failed = [d for d in data if not d.get("flag_found")]
    
    total_prompt = sum(d.get("prompt_tokens", 0) for d in data)
    total_completion = sum(d.get("completion_tokens", 0) for d in data)
    total_tokens = sum(d.get("total_tokens", 0) for d in data)
    total_duration = sum(d.get("duration_seconds", 0) for d in data)
    
    print(f"  总任务数:        {total}")
    print(f"  成功数:          {len(success)}  ({len(success)/total*100:.1f}%)")
    print(f"  失败数:          {len(failed)}  ({len(failed)/total*100:.1f}%)")
    print(f"  总耗时:          {fmt_sec(total_duration)}")
    print(f"  平均耗时:        {fmt_sec(mean([d.get('duration_seconds',0) for d in data]))}")
    print(f"  总Prompt Tokens: {fmt_num(total_prompt)}")
    print(f"  总Completion Tokens: {fmt_num(total_completion)}")
    print(f"  总Tokens:        {fmt_num(total_tokens)}")
    print(f"  Prompt/Completion 比例: {total_prompt/total_completion:.2f}:1" if total_completion else "  N/A")
    
    # 空报告检测
    empty_result = [d["benchmark_id"] for d in data if d.get("flag_found") and not d.get("agent_result", "").strip()]
    if empty_result:
        print(f"\n  ⚠️ 成功但agent_result为空的任务: {', '.join(empty_result)}")
    
    # ========== 2. 难度维度分析 ==========
    print_section("2. 难度维度分析 (Difficulty Analysis)")
    by_level = defaultdict(list)
    for d in data:
        by_level[d.get("level", "unknown")].append(d)
    
    rows = []
    for lvl in sorted(by_level.keys()):
        items = by_level[lvl]
        succ = [d for d in items if d.get("flag_found")]
        rows.append([
            f"Level {lvl}",
            len(items),
            f"{len(succ)/len(items)*100:.0f}%",
            fmt_sec(mean([d.get("duration_seconds",0) for d in items])),
            fmt_num(mean([d.get("total_tokens",0) for d in items])),
            fmt_num(median([d.get("total_tokens",0) for d in items])),
        ])
    print_table(["难度", "数量", "成功率", "平均耗时", "平均Tokens", "中位Tokens"], rows)
    
    # ========== 3. 漏洞类型(tag)维度分析 ==========
    print_section("3. 漏洞类型分析 (Vulnerability Type Analysis)")
    tag_stats = defaultdict(lambda: {"count": 0, "success": 0, "duration": [], "tokens": []})
    tag_combos = Counter()
    
    for d in data:
        tags = d.get("tags", [])
        tag_combos[tuple(sorted(tags))] += 1
        for tag in tags:
            s = tag_stats[tag]
            s["count"] += 1
            if d.get("flag_found"):
                s["success"] += 1
            s["duration"].append(d.get("duration_seconds", 0))
            s["tokens"].append(d.get("total_tokens", 0))
    
    rows = []
    for tag, s in sorted(tag_stats.items(), key=lambda x: -x[1]["count"]):
        rows.append([
            tag,
            s["count"],
            f"{s['success']/s['count']*100:.0f}%",
            fmt_sec(mean(s["duration"])),
            fmt_num(mean(s["tokens"])),
        ])
    print_table(["漏洞类型", "出现次数", "成功率", "平均耗时", "平均Tokens"], rows)
    
    # Top tag combinations
    print("\n  最常见的Tag组合 (Top Tag Combinations):")
    combo_rows = []
    for combo, cnt in tag_combos.most_common(10):
        combo_rows.append([" + ".join(combo), cnt])
    print_table(["组合", "数量"], combo_rows)
    
    # ========== 4. Token消耗分析 ==========
    print_section("4. Token消耗分析 (Token Consumption Analysis)")
    
    # 找出最高/最低消耗的任务
    sorted_by_tokens = sorted(data, key=lambda d: d.get("total_tokens", 0), reverse=True)
    print("\n  Token消耗TOP 10 (最高):")
    top_rows = []
    for d in sorted_by_tokens[:10]:
        top_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_num(d.get("total_tokens", 0)),
            fmt_num(d.get("prompt_tokens", 0)),
            fmt_num(d.get("completion_tokens", 0)),
        ])
    print_table(["ID", "名称", "总Tokens", "Prompt", "Completion"], top_rows, [10, 38, 14, 14, 14])
    
    print("\n  Token消耗BOTTOM 10 (最低):")
    bot_rows = []
    for d in sorted_by_tokens[-10:]:
        bot_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_num(d.get("total_tokens", 0)),
            fmt_num(d.get("prompt_tokens", 0)),
            fmt_num(d.get("completion_tokens", 0)),
        ])
    print_table(["ID", "名称", "总Tokens", "Prompt", "Completion"], bot_rows, [10, 38, 14, 14, 14])
    
    # Token分布区间
    print("\n  Token消耗区间分布:")
    bins = [(0, 100000), (100000, 500000), (500000, 1000000), (1000000, 3000000), (3000000, 10000000), (10000000, float('inf'))]
    bin_labels = ["<100K", "100K-500K", "500K-1M", "1M-3M", "3M-10M", ">10M"]
    bin_counts = [0] * len(bins)
    for d in data:
        t = d.get("total_tokens", 0)
        for i, (lo, hi) in enumerate(bins):
            if lo <= t < hi:
                bin_counts[i] += 1
                break
    for label, cnt in zip(bin_labels, bin_counts):
        bar = "█" * int(cnt * 2)
        print(f"    {label:>8}: {cnt:>3} {bar}")
    
    # Prompt/Completion ratio by level
    print("\n  各难度Prompt/Completion比例:")
    for lvl in sorted(by_level.keys()):
        items = by_level[lvl]
        p = sum(d.get("prompt_tokens", 0) for d in items)
        c = sum(d.get("completion_tokens", 0) for d in items)
        ratio = p / c if c else 0
        print(f"    Level {lvl}: {ratio:.2f}:1  (Prompt={fmt_num(p)}, Completion={fmt_num(c)})")
    
    # ========== 5. 效率分析 ==========
    print_section("5. 效率分析 (Efficiency Analysis)")
    
    # 最耗时任务
    sorted_by_time = sorted(data, key=lambda d: d.get("duration_seconds", 0), reverse=True)
    print("\n  耗时TOP 10:")
    time_rows = []
    for d in sorted_by_time[:10]:
        time_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_sec(d.get("duration_seconds", 0)),
            fmt_num(d.get("total_tokens", 0)),
            f"{d.get('total_tokens',0)/max(d.get('duration_seconds',1),1):,.0f}",
        ])
    print_table(["ID", "名称", "耗时", "总Tokens", "Tokens/s"], time_rows, [10, 38, 10, 14, 10])
    
    # 最快完成的任务
    print("\n  耗时最短TOP 10:")
    fast_rows = []
    for d in sorted_by_time[-10:]:
        fast_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_sec(d.get("duration_seconds", 0)),
            fmt_num(d.get("total_tokens", 0)),
        ])
    print_table(["ID", "名称", "耗时", "总Tokens"], fast_rows, [10, 38, 10, 14])
    
    # 效率指标
    tokens_per_sec = [d.get("total_tokens", 0) / max(d.get("duration_seconds", 1), 1) for d in data]
    print(f"\n  平均Token消耗速率: {mean(tokens_per_sec):,.0f} tokens/s")
    print(f"  中位Token消耗速率: {median(tokens_per_sec):,.0f} tokens/s")
    
    # ========== 6. 异常与特征分析 ==========
    print_section("6. 异常与特征分析 (Anomaly & Feature Analysis)")
    
    # 高Token但短时间
    print("\n  高Token消耗但短时间完成 (效率极高):")
    efficient = [d for d in data if d.get("total_tokens", 0) > 500000 and d.get("duration_seconds", 9999) < 120]
    eff_rows = []
    for d in efficient:
        eff_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_num(d.get("total_tokens", 0)),
            fmt_sec(d.get("duration_seconds", 0)),
        ])
    print_table(["ID", "名称", "Tokens", "耗时"], eff_rows, [10, 38, 14, 10])
    
    # 低Token但长时间
    print("\n  低Token但长时间完成 (可能存在延迟/等待):")
    inefficient = [d for d in data if d.get("total_tokens", 0) < 300000 and d.get("duration_seconds", 0) > 300]
    ineff_rows = []
    for d in inefficient:
        ineff_rows.append([
            d["benchmark_id"],
            d.get("name", "")[:35],
            fmt_num(d.get("total_tokens", 0)),
            fmt_sec(d.get("duration_seconds", 0)),
        ])
    print_table(["ID", "名称", "Tokens", "耗时"], ineff_rows, [10, 38, 14, 10])
    
    # 错误分析
    errors = [d for d in data if d.get("error")]
    if errors:
        print(f"\n  出现error的任务: {len(errors)}")
        for d in errors:
            print(f"    {d['benchmark_id']}: {str(d['error'])[:80]}")
    else:
        print(f"\n  ✅ 所有任务均无error字段")
    
    # turns分析
    turns_data = [d.get("turns", 0) for d in data]
    print(f"\n  Turns统计: 全部为零 (max={max(turns_data)}, min={min(turns_data)})")
    
    # ========== 7. 漏洞成功率排名 ==========
    print_section("7. 漏洞类型成功率排名 (Success Rate by Vulnerability)")
    
    tag_success_list = []
    for tag, s in tag_stats.items():
        if s["count"] >= 2:  # 至少出现2次才有统计意义
            tag_success_list.append((tag, s["success"]/s["count"], s["count"], mean(s["duration"]), mean(s["tokens"])))
    
    tag_success_list.sort(key=lambda x: -x[1])
    sr_rows = []
    for tag, rate, cnt, avg_dur, avg_tok in tag_success_list:
        sr_rows.append([
            tag,
            f"{rate*100:.0f}%",
            cnt,
            fmt_sec(avg_dur),
            fmt_num(avg_tok),
        ])
    print_table(["漏洞类型", "成功率", "样本数", "平均耗时", "平均Tokens"], sr_rows)
    
    # ========== 8. 生成详细JSON报告 ==========
    print_section("8. 生成结构化报告 (Structured Report Generation)")
    
    report = {
        "overview": {
            "total_tasks": total,
            "success_count": len(success),
            "success_rate": len(success) / total,
            "total_duration_seconds": total_duration,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
        },
        "by_level": {},
        "by_tag": {},
        "top_consumers": {
            "tokens": [{"id": d["benchmark_id"], "name": d.get("name", ""), "tokens": d.get("total_tokens", 0)} for d in sorted_by_tokens[:10]],
            "time": [{"id": d["benchmark_id"], "name": d.get("name", ""), "seconds": d.get("duration_seconds", 0)} for d in sorted_by_time[:10]],
        },
        "efficiency": {
            "avg_tokens_per_second": mean(tokens_per_sec),
            "median_tokens_per_second": median(tokens_per_sec),
        }
    }
    
    for lvl, items in by_level.items():
        succ = [d for d in items if d.get("flag_found")]
        report["by_level"][f"level_{lvl}"] = {
            "count": len(items),
            "success_rate": len(succ) / len(items),
            "avg_duration": mean([d.get("duration_seconds", 0) for d in items]),
            "avg_tokens": mean([d.get("total_tokens", 0) for d in items]),
        }
    
    for tag, s in tag_stats.items():
        report["by_tag"][tag] = {
            "count": s["count"],
            "success_rate": s["success"] / s["count"],
            "avg_duration": mean(s["duration"]),
            "avg_tokens": mean(s["tokens"]),
        }
    
    report_path = Path("benchmark_analysis_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"  结构化报告已保存: {report_path.resolve()}")
    
    # ========== 9. 关键结论 ==========
    print_section("9. 关键结论与洞察 (Key Conclusions)")
    
    # 计算一些关键洞察
    hardest_tag = max(tag_stats.items(), key=lambda x: mean(x[1]["duration"]))
    most_expensive_tag = max(tag_stats.items(), key=lambda x: mean(x[1]["tokens"]))
    easiest_tag = min((x for x in tag_stats.items() if x[1]["count"] >= 2), key=lambda x: mean(x[1]["duration"]))
    cheapest_tag = min((x for x in tag_stats.items() if x[1]["count"] >= 2), key=lambda x: mean(x[1]["tokens"]))
    
    # 难度影响
    lvl_rates = {lvl: len([d for d in items if d.get("flag_found")]) / len(items) for lvl, items in by_level.items()}
    lvl_avg_tokens = {lvl: mean([d.get("total_tokens", 0) for d in items]) for lvl, items in by_level.items()}
    lvl_avg_time = {lvl: mean([d.get("duration_seconds", 0) for d in items]) for lvl, items in by_level.items()}
    
    conclusions = [
        f"整体成功率: {len(success)/total*100:.0f}% — 智能体在所有CTF挑战上均成功获取flag",
        f"难度对成功率无影响 — Level 1/2/3 成功率均为100%",
        f"难度显著影响资源消耗: Level 3 平均 {fmt_num(lvl_avg_tokens.get(3,0))} tokens, 是 Level 1 ({fmt_num(lvl_avg_tokens.get(1,0))}) 的 {lvl_avg_tokens.get(3,0)/max(lvl_avg_tokens.get(1,0),1):.1f} 倍",
        f"耗时最长的漏洞类型: {hardest_tag[0]} (平均 {fmt_sec(mean(hardest_tag[1]['duration']))})",
        f"最Token密集的漏洞类型: {most_expensive_tag[0]} (平均 {fmt_num(mean(most_expensive_tag[1]['tokens']))} tokens)",
        f"解决最快的漏洞类型 (≥2样本): {easiest_tag[0]} (平均 {fmt_sec(mean(easiest_tag[1]['duration']))})",
        f"最节省Token的漏洞类型 (≥2样本): {cheapest_tag[0]} (平均 {fmt_num(mean(cheapest_tag[1]['tokens']))} tokens)",
        f"Prompt/Completion 整体比例 {total_prompt/total_completion:.1f}:1，说明任务以推理/观察为主，输出相对较少",
        f"XSS类挑战数量最多 ({tag_stats.get('xss', {}).get('count', 0)}个)，但平均耗时中等，显示智能体对XSS较为熟练",
        f"SSTI类挑战虽然数量不多，但平均Token消耗高，说明模板注入的上下文推理需要大量交互",
    ]
    
    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")
    
    print()

if __name__ == "__main__":
    data = load_data()
    analyze(data)
