---
name: nmap
description: Canonical Nmap CLI syntax, strict staged scanning workflow, and sandbox-safe bounded scan patterns with timeout backoff.
---

# Nmap CLI Playbook

Official docs:
- https://nmap.org/book/man-briefoptions.html
- https://nmap.org/book/man.html
- https://nmap.org/book/man-performance.html

## Staged Scanning Doctrine (HARD CONSTRAINT)

Nmap scans MUST follow a **staged escalation** pattern. NEVER jump to a broad sweep on the first call.

### Stage 1: Discovery (MANDATORY first step)
Goal: Find live hosts and open ports quickly.
- Use `--top-ports 100` or smaller explicit port lists (`-p 22,80,443,8080,8443`).
- No service detection (`-sV`), no scripts (`-sC`) at this stage.
- Tight timeouts: `--host-timeout 60s`.
- Baseline command:
  `nmap -n -Pn --open --top-ports 100 -T4 --max-retries 1 --host-timeout 60s -oA nmap_stage1 <target>`

### Stage 2: Service Enrichment (run ONLY on ports found in Stage 1)
Goal: Identify services and versions on discovered ports.
- Use `-sV -sC` scoped to the exact ports found: `-p <comma_ports>`.
- Add `--script-timeout 30s` and `--host-timeout 3m`.
- Baseline command:
  `nmap -n -Pn -sV -sC -p <ports> --script-timeout 30s --host-timeout 3m -oA nmap_stage2 <target>`

### Stage 3: Full Port Scan (EXPLICIT AUTHORIZATION REQUIRED)
Goal: Only run when Stage 1 found nothing useful AND the user explicitly asked for comprehensive coverage.
- `-p-` or `--top-ports 1000` are Stage 3 ONLY.
- Before escalating, ask: "Stage 1 discovered no open ports on common services. Do you want to run a full port scan (`-p-`) which may take 10-30 minutes?"
- If proceeding, use `-T3` or lower and `--max-retries 1` to bound duration.
- Baseline command:
  `nmap -n -Pn -p- -sV --open -T3 --max-retries 1 --host-timeout 10m -oA nmap_stage3 <target>`

### Stage 4: Vulnerability Scripts (run ONLY on confirmed services)
Goal: Run targeted NSE scripts against known service versions.
- Never run `--script=vuln` against all ports blindly.
- Scope scripts to the service: `--script=http-*` for HTTP, `--script=ssh-*` for SSH, etc.
- Baseline command:
  `nmap -n -Pn -p <ports> --script=<service-family>-vuln --script-timeout 30s -oA nmap_stage4 <target>`

## Timeout & Backoff Rules

If ANY nmap invocation hits a timeout or runs longer than expected, apply this backoff sequence:

1. **First timeout** (>60s for Stage 1, >3m for Stage 2):
   - Reduce port scope by 50% (`--top-ports 100` -> `--top-ports 50` or `-p 22,80,443`).
   - Lower timing: `-T4` -> `-T3`.
   - Lower retries: `--max-retries 1` (already minimal).
   - Retry once.

2. **Second timeout** (same stage):
   - Reduce to the absolute minimum: `-p 22,80,443`.
   - Use `-T2` and `--host-timeout 30s`.
   - If this also times out, report "Host/network appears heavily filtered or very slow. Pivot to alternative reconnaissance (e.g., web probing, DNS enumeration)."

3. **Never retry the exact same command** after a timeout. Each retry MUST have a smaller scope or lower timing template.

## High-signal flags reference
- `-n` skip DNS resolution
- `-Pn` skip host discovery when ICMP/ping is filtered
- `-sS` SYN scan (root/privileged)
- `-sT` TCP connect scan (no raw-socket privilege)
- `-sV` detect service versions
- `-sC` run default NSE scripts
- `-p <ports>` explicit ports (`-p-` for all TCP ports — **Stage 3 only**)
- `--top-ports <n>` quick common-port sweep (**Stage 1 default**)
- `--open` show only hosts with open ports
- `-T<0-5>` timing template (`-T4` common, `-T3` for broader scans)
- `--max-retries <n>` cap retransmissions
- `--host-timeout <time>` give up on very slow hosts
- `--script-timeout <time>` bound NSE script runtime
- `-oA <prefix>` output in normal/XML/grepable formats

## No-root fallback
If `nmap` fails with "You requested a scan type which requires root privileges":
- Replace `-sS` with `-sT`.
- Keep all other constraints identical.

## Agent-safe baseline commands by stage

Stage 1 (Discovery):
```
nmap -n -Pn --open --top-ports 100 -T4 --max-retries 1 --host-timeout 60s -oA nmap_s1 <host>
```

Stage 2 (Service enrichment, ports from Stage 1):
```
nmap -n -Pn -sV -sC -p <ports> --script-timeout 30s --host-timeout 3m -oA nmap_s2 <host>
```

Stage 3 (Full port — explicit auth only):
```
nmap -n -Pn -p- -sV --open -T3 --max-retries 1 --host-timeout 10m -oA nmap_s3 <host>
```

## Critical correctness rules
- **ALWAYS** start with Stage 1. `-p-` on the first call is a protocol violation.
- **ALWAYS** set target scope explicitly.
- **ALWAYS** set a timeout boundary with `--host-timeout`; add `--script-timeout` whenever NSE scripts are involved.
- **NEVER** run `-p-` unless Stage 1 returned zero open ports AND the user explicitly requested full coverage.
- Do not spam traffic; start with the smallest port set that can answer the question.
- Prefer `naabu` for broad port discovery; use `nmap` for scoped verification/enrichment.

## Failure recovery
- If host appears down unexpectedly, rerun Stage 1 with `-Pn`.
- If scan stalls, apply the Timeout & Backoff Rules above.
- If scripts run too long, add `--script-timeout` or switch to targeted scripts.

If uncertain, query web_search with:
`site:nmap.org/book nmap <flag>`
