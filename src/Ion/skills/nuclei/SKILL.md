---
name: nuclei
description: Exact Nuclei command structure, template selection, staged scanning workflow, and bounded high-throughput execution controls with timeout backoff.
---

# Nuclei CLI Playbook

Official docs:
- https://docs.projectdiscovery.io/opensource/nuclei/running
- https://docs.projectdiscovery.io/opensource/nuclei/mass-scanning-cli
- https://github.com/projectdiscovery/nuclei

## Staged Scanning Doctrine (HARD CONSTRAINT)

Nuclei scans MUST follow a **staged escalation** pattern. NEVER run an unscoped broad template sweep on the first call.

### Stage 1: High-Signal Targeted Scan (MANDATORY first step)
Goal: Find the most impactful vulnerabilities with minimal noise and time.
- Filter by severity: `-s critical,high`.
- Use a small, high-confidence template set OR `-as` (automatic-scan) combined with severity filter.
- Conservative concurrency: `-rl 30 -c 10 -bs 10`.
- Short timeout per request: `-timeout 10 -retries 1`.
- Disable OAST if not needed: `-ni`.
- Baseline command:
  `nuclei -u <target> -s critical,high -ni -rl 30 -c 10 -bs 10 -timeout 10 -retries 1 -silent -j -o nuclei_stage1.jsonl`

### Stage 2: Expanded Coverage (run if Stage 1 completed successfully)
Goal: Add medium-severity findings and tech-mapped templates.
- Expand severity: `-s critical,high,medium`.
- Enable automatic scan for tech-mapped templates: `-as`.
- Moderate concurrency: `-rl 50 -c 20 -bs 20`.
- Baseline command:
  `nuclei -u <target> -as -s critical,high,medium -ni -rl 50 -c 20 -bs 20 -timeout 10 -retries 1 -j -o nuclei_stage2.jsonl`

### Stage 3: Full Template Sweep (EXPLICIT AUTHORIZATION REQUIRED)
Goal: Run all applicable templates for comprehensive assessment.
- Only run when the user explicitly requests "full scan", "comprehensive scan", or "all templates".
- No severity filter (or `-s info,low,medium,high,critical`).
- Before escalating, warn: "A full template sweep may take 15+ minutes and generate significant traffic. Proceed?"
- Baseline command:
  `nuclei -u <target> -as -rl 50 -c 20 -bs 20 -timeout 10 -retries 1 -stats -j -o nuclei_stage3.jsonl`

## Timeout & Backoff Rules

If ANY nuclei invocation runs longer than expected or appears hung:

1. **First timeout / excessive duration** (>5m for Stage 1, >15m for Stage 2):
   - Reduce rate limit by 50%: `-rl 30` -> `-rl 15`.
   - Reduce concurrency by 50%: `-c 10 -bs 10` -> `-c 5 -bs 5`.
   - If using `-as`, switch to explicit template tags or severity-only filtering to reduce template count.
   - Retry once with the reduced parameters.

2. **Second timeout / excessive duration**:
   - Reduce to minimum viable scan: `-s critical` only, `-rl 10 -c 3 -bs 3`.
   - If this also times out, report "Target appears unresponsive to automated template scanning. Pivot to manual probing or alternative tools."

3. **Never retry the exact same command** after a timeout. Each retry MUST have reduced `-rl`, `-c`, `-bs`, or stricter template filters.

## High-signal flags reference
- `-u, -target <url>` single target
- `-l, -list <file>` targets file
- `-im, -input-mode <mode>` list/burp/jsonl/yaml/openapi/swagger
- `-t, -templates <path|tag>` explicit template path(s)
- `-tags <tag1,tag2>` run by tag
- `-s, -severity <critical,high,...>` severity filter
- `-as, -automatic-scan` tech-mapped automatic scan
- `-ni, -no-interactsh` disable OAST/interactsh requests
- `-rl, -rate-limit <n>` global request rate cap
- `-c, -concurrency <n>` template concurrency
- `-bs, -bulk-size <n>` hosts in parallel per template
- `-timeout <seconds>` request timeout
- `-retries <n>` retries
- `-stats` periodic scan stats output
- `-silent` findings-only output
- `-j, -jsonl` JSONL output
- `-o <file>` output file

## Common patterns
- Focused severity scan (Stage 1 default):
  `nuclei -u https://target.tld -s critical,high -ni -silent -j -o nuclei_s1.jsonl`
- Tech-mapped expanded scan (Stage 2):
  `nuclei -u https://target.tld -as -s critical,high,medium -ni -rl 50 -c 20 -bs 20 -timeout 10 -retries 1 -j -o nuclei_s2.jsonl`
- Tag-driven targeted run:
  `nuclei -u https://target.tld -tags cve -s critical,high -ni -silent -j -o nuclei_cve.jsonl`
- Explicit templates on confirmed tech stack:
  `nuclei -u https://target.tld -t http/cves/ -t http/misconfiguration/ -rl 30 -c 10 -bs 10 -j -o nuclei_tech.jsonl`

## Critical correctness rules
- **ALWAYS** start with Stage 1 (`-s critical,high`). An unscoped `-as` alone on the first call is a protocol violation.
- Provide a template selection method (`-s`, `-tags`, or `-t`); avoid unscoped broad runs.
- Keep `-rl`, `-c`, and `-bs` explicit for predictable resource use.
- Use `-ni` when outbound interactsh/OAST traffic is not expected or not allowed.
- Use structured output (`-j -o <file>`) for automation.

## Failure recovery
- If performance degrades, lower `-c/-bs` before lowering `-rl`.
- If findings are unexpectedly empty, verify template selection (`-as` vs explicit `-t/-tags`) and that the target is reachable.
- If scan duration grows, apply the Timeout & Backoff Rules above.

If uncertain, query web_search with:
`site:docs.projectdiscovery.io nuclei <flag> running`
