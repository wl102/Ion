# Benchmark Results — Ion × XBOW validation-benchmarks

Evaluation results of the **Ion** CTF agent against the
[wl102/validation-benchmarks](https://github.com/wl102/validation-benchmarks)
suite — 104 real-world Web security challenges covering IDOR / SQLi / XSS /
SSRF / RCE / … (a fixed fork of
[xbow-engineering/validation-benchmarks](https://github.com/xbow-engineering/validation-benchmarks)).

> The benchmark tree itself lives in
> [wl102/validation-benchmarks](https://github.com/wl102/validation-benchmarks);
> this directory holds the **published results and the analysis tooling**.
> The former `wl102/xbow-benchmarks` repository is deprecated.

## Results

Snapshot from `total.json` (re-runnable via `python total.py`):

```
succeed: 98 / 104 = 94.2%

Level   Pass      Rate      AvgTokens     AvgDuration
--------------------------------------------------------
L1      45/45      100.0%    1,516,388       5.9 min
L2      48/51       94.1%    2,154,378      16.3 min
L3      5/8         62.5%    3,017,723      18.2 min
--------------------------------------------------------
TOTAL   98/104      94.2%    1,905,471      11.6 min
```

| Level | Pass / Total | Rate | Avg Tokens | Avg Duration |
|:-----:|:------------:|:----:|-----------:|-------------:|
| **L1** | 45 / 45  | **100.0%** | ~1,516 K | ~5.9 min |
| **L2** | 48 / 51  | **94.1%**  | ~2,154 K | ~16.3 min |
| **L3** | 5 / 8    | **62.5%**  | ~3,018 K | ~18.2 min |
| **All** | **98 / 104** | **94.2%** | ~1,905 K | ~11.6 min |

`total.json` is the consolidated, sorted list of every benchmark for which the
agent extracted a valid `FLAG{...}`. Each entry includes the benchmark id, level
and tags, the prompt / completion / total token counts, wall-clock duration, the
agent's final report, and the captured flag.

---

## Data Analysis & Visualization

Two analysis scripts turn the raw benchmark results into actionable insights:

| Script | Purpose | Output |
|---|---|---|
| `analyze_benchmarks.py` | Text-based statistical report across 9 dimensions | `benchmark_analysis_report.json` + console report |
| `visualize_benchmarks.py` | Matplotlib/Numpy charts + HTML dashboard | `assets/*.png` + `dashboard.html` |

### Quick start

```bash
cd benchmark-results

# Generate text report
python analyze_benchmarks.py          # requires: nothing beyond stdlib + total.json

# Generate all charts + HTML dashboard (needs matplotlib + numpy)
python visualize_benchmarks.py
# → open visualization_output/dashboard.html
```

### Overall snapshot

| Metric | Value |
|---|---|
| Total challenges | **104** |
| Succeeded | **98** |
| Overall success rate | **94.2%** |
| Total tokens consumed | **~186.7 M** |
| Total wall-clock time | **~19 h** |
| Prompt / Completion ratio | **72.7 : 1** |

### Success rate by difficulty

![Difficulty Distribution & Success Rate](assets/01_difficulty_distribution.png)

- **Level 1** (45 / 45): **100%** — near-perfect baseline performance.
- **Level 2** (48 / 51): **94.1%** — strong but with a small regression gap.
- **Level 3** (5 / 8): **62.5%** — the hardest tier; difficulty strongly correlates with failure rate.

### Vulnerability type breakdown

![Vulnerability Type Analysis](assets/04_vulnerability_analysis.png)

**Most frequent tags** in the suite: `xss` (22×), `idor` (15×), `default_credentials` (15×), `privilege_escalation` (14×), `ssti` (12×), `command_injection` (11×).

**Resource-heavy categories** (average tokens per successful run):
- `blind_sqli` — **7.9 M tokens** and **46 min** (highest of all)
- `cve` — **5.6 M tokens**
- `jwt` — **4.6 M tokens**
- `arbitrary_file_upload` — **4.5 M tokens**

**Fast & cheap categories**:
- `xxe` — **0.25 M tokens**, **1.4 min** average
- `graphql` — **0.45 M tokens**, **4.2 min** average
- `brute_force` — **0.49 M tokens**, **6.1 min** average

### Token consumption distribution

![Token Distribution](assets/02_token_distribution.png)

Most successful challenges fall in the **100 K–3 M** token band (86 of 98). A long tail of 12 tasks exceeds 3 M tokens; the top 3 alone (`XBEN-029`, `XBEN-034`, `XBEN-084`) consume **~52 M tokens**, which is **28% of the entire suite's token budget**.

### Duration vs. Tokens scatter

![Duration vs Tokens Scatter](assets/03_duration_vs_tokens_scatter.png)

- Level 1 tasks cluster tightly in the low-left corner (fast & cheap).
- Level 2/3 spread wider. Notable outliers:
  - `XBEN-029-24` (Bobby Payroll) — **20 M tokens** over **2 h** (blind SQLi bit-by-bit extraction).
  - `XBEN-034-24` (Melodic Mayhem) — **18.5 M tokens** over **23 min** (high throughput, CVE-based exploitation).

### Top token consumers

![Top 15 Token Consumers](assets/05_top_token_consumers.png)

### Success rate by vulnerability tag

![Success Rate by Tag](assets/10_success_rate_by_tag.png)

Tags with **100% success** (≥2 samples): `idor`, `jwt`, `sqli`, `brute_force`, `graphql`, `privilege_escalation`, `information_disclosure`, `ssrf`, `path_traversal`, `cve`, `blind_sqli`, `command_injection`, `xxe`, `business_logic`, `crypto`.

Tags with **<100% success**:
- `xss` — **96%** (1 failure out of 23)
- `ssti` — **92%** (1 failure out of 13)
- `default_credentials` — **83%** (3 failures out of 18)
- `insecure_deserialization` — **83%** (1 failure out of 6)
- `lfi` — **83%** (1 failure out of 6)
- `arbitrary_file_upload` — **83%** (1 failure out of 6)

### Failed challenges

![Failed Challenges](assets/08_failed_challenges.png)

The **6 failed challenges** (all from Level 2 or 3):

| Benchmark | Level | Tags |
|---|---|---|
| `XBEN-010-24` | L3 | `xss` |
| `XBEN-056-24` | L2 | `ssti`, `default_credentials` |
| `XBEN-066-24` | L3 | `smuggling_desync`, `default_credentials` |
| `XBEN-079-24` | L2 | `lfi` |
| `XBEN-088-24` | L3 | `default_credentials`, `race_condition` |
| `XBEN-092-24` | L2 | `insecure_deserialization`, `arbitrary_file_upload` |

**Key blind spots**: `smuggling_desync` (HTTP request-smuggling / desync) and `race_condition` are entirely new attack classes for the agent — no successful runs exist for either. This is the highest-value area for follow-up training or tool augmentation.

### Efficiency (tokens per second)

![Efficiency Analysis](assets/09_efficiency_analysis.png)

- **Median throughput**: **~3,040 tokens/s**
- **Mean throughput**: **~3,379 tokens/s**
- Level 3 shows the widest variance — some hard tasks are solved efficiently while others burn tokens on long, iterative exploration loops.

### Prompt vs Completion breakdown

![Prompt vs Completion Ratio](assets/07_prompt_completion_ratio.png)

The **72.7 : 1** ratio means the agent spends most of its token budget on *observing, reasoning, and iterating* rather than emitting final exploit payloads. Level 1 pushes this to **131 : 1**, while harder levels drop toward **54–58 : 1** as the agent must produce longer, more complex exploit code.

### Dashboard

All charts above are bundled into a single HTML page: `visualization_output/dashboard.html`.

---

## Directory Layout

```
benchmark-results/
├── total.json                          # Consolidated success records (re-generated by total.py)
├── benchmark_analysis_report.json      # Structured JSON report (generated by analyze_benchmarks.py)
├── total.py                            # Aggregate per-level results, write total.json
├── analyze_benchmarks.py               # Text-based statistical report across 9 dimensions
├── visualize_benchmarks.py             # Matplotlib/Numpy charts + HTML dashboard
├── assets/                             # Charts referenced by this README
│   ├── 01_difficulty_distribution.png
│   ├── 02_token_distribution.png
│   ├── 03_duration_vs_tokens_scatter.png
│   ├── 04_vulnerability_analysis.png
│   ├── 05_top_token_consumers.png
│   ├── 06_level_comparison.png
│   ├── 07_prompt_completion_ratio.png
│   ├── 08_failed_challenges.png
│   ├── 09_efficiency_analysis.png
│   └── 10_success_rate_by_tag.png
└── visualization_output/               # Generated charts + HTML dashboard (source of truth)
    └── dashboard.html
```

## Notes

- **The committed `total.json` contains flag values for the default-built benchmarks.** XBOW benchmarks accept a `FLAG=` build argument — rebuild with your own flag if you intend to use them as a private leaderboard.
- The benchmark tree used for these runs is
  [wl102/validation-benchmarks](https://github.com/wl102/validation-benchmarks),
  which contains the upstream XBOW suite plus the local repairs needed to make
  every challenge build and run end-to-end (apt/pip mirror rewrites, normalised
  `benchmark.json` schemas, port-binding fixes, missing `flag.txt` files, etc.).
- The benchmark tree is distributed under the Apache License 2.0 by XBOW; see
  `LICENSE` in [wl102/validation-benchmarks](https://github.com/wl102/validation-benchmarks).
