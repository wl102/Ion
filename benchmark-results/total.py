from pathlib import Path
import json
import re
from collections import defaultdict

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


def extract_number(id: str) -> int:
    match = re.search(r"XBEN-(\d+)", id)
    return int(match.group(1)) if match else 10**9


def normalize_level(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


level_total: dict[int, int] = defaultdict(int)
for d in sorted(BENCH_DIR.iterdir()) if BENCH_DIR.exists() else []:
    meta = d / "benchmark.json"
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        level_total[normalize_level(data.get("level"))] += 1
total_benchmarks = sum(level_total.values())


succeed: dict[str, dict] = {}
for path in ROOT.glob("*.json"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        continue
    results = data if isinstance(data, list) else data.get("results", []) if isinstance(data, dict) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("flag_found"):
            bid = item.get("benchmark_id")
            if bid:
                succeed[bid] = item


level_succ: dict[int, list[dict]] = defaultdict(list)
for item in succeed.values():
    level_succ[normalize_level(item.get("level"))].append(item)


def avg(xs: list[float]) -> float:
    xs = [x for x in xs if x]
    return sum(xs) / len(xs) if xs else 0.0


print(f"succeed: {len(succeed)} / {total_benchmarks} = {len(succeed) / total_benchmarks * 100:.1f}%" if total_benchmarks else f"succeed: {len(succeed)}")
print()
print(f"{'Level':<8}{'Pass':<10}{'Rate':<10}{'AvgTokens':<14}{'AvgDuration':<14}")
print("-" * 56)
for lvl in sorted(level_total):
    items = level_succ.get(lvl, [])
    n_succ, n_tot = len(items), level_total[lvl]
    rate = n_succ / n_tot * 100 if n_tot else 0
    avg_tok = avg([x.get("total_tokens", 0) for x in items])
    avg_dur = avg([x.get("duration_seconds", 0) for x in items])
    print(f"L{lvl:<7}{n_succ}/{n_tot:<8}{rate:5.1f}%   {avg_tok:>10,.0f}    {avg_dur / 60:>6.1f} min")

print(f"Total tokens: {sum([succeed[x].get("total_tokens", 0) for x in succeed])}")

all_tokens = [x.get("total_tokens", 0) for x in succeed.values()]
all_durs = [x.get("duration_seconds", 0) for x in succeed.values()]
print("-" * 56)
print(f"{'TOTAL':<8}{len(succeed)}/{total_benchmarks:<8}{(len(succeed) / total_benchmarks * 100 if total_benchmarks else 0):5.1f}%   {avg(all_tokens):>10,.0f}    {avg(all_durs) / 60:>6.1f} min")

print("\nSucceeded IDs:")
sorted_succeed = []
for bid in sorted(succeed, key=extract_number):
    b = succeed[bid]
    sorted_succeed.append(b)
    print(f"  {bid}  L{b.get('level', 0)}  tokens={b.get('total_tokens', 0):>9}  dur={b.get('duration_seconds', 0):>7.1f}s")

with open(ROOT / "total.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(sorted_succeed, ensure_ascii=False, indent=2))