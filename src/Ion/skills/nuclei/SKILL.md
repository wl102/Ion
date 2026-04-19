---
name: nuclei
description: Fast and customizable vulnerability scanner based on YAML templates. Use when you need to scan for known CVEs, misconfigurations, or security vulnerabilities on web targets.
compatibility: Requires nuclei to be installed on the system.
metadata:
  category: vulnerability-scanning
  tool: nuclei
---

# Nuclei Skill

## When to use this skill

Use this skill when the task involves:
- Scanning for known CVEs
- Detecting security misconfigurations
- Finding exposed panels or sensitive files
- Running template-based vulnerability scans

## Basic usage

Scan a single URL:

```bash
nuclei -u <target>
```

Scan with specific severity filters:

```bash
nuclei -u <target> -severity critical,high,medium
```

Scan a list of URLs:

```bash
nuclei -l urls.txt
```

## Common flags

| Flag | Description |
|------|-------------|
| `-u <url>` | Target URL |
| `-l <file>` | List of target URLs |
| `-severity <levels>` | Filter by severity (critical, high, medium, low, info) |
| `-t <templates>` | Specify templates to use |
| `-silent` | Silent mode, only show findings |
| `-json` | Output in JSON format |
| `-o <file>` | Output results to file |

## Safety

- Only scan targets you own or have explicit permission to test.
- Some templates may be intrusive; review before running against production.
