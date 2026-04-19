---
name: dirsearch
description: Web path scanner for finding hidden directories and files. Use when you need to brute-force discover accessible paths, admin panels, backup files, or hidden endpoints on a web server.
compatibility: Requires dirsearch to be installed on the system.
metadata:
  category: reconnaissance
  tool: dirsearch
---

# Dirsearch Skill

## When to use this skill

Use this skill when the task involves:
- Discovering hidden directories and files
- Finding admin panels or login pages
- Locating backup files or source code leaks
- Enumerating API endpoints

## Basic usage

Scan a single URL:

```bash
dirsearch -u <target>
```

Scan with specific extensions:

```bash
dirsearch -u <target> -e php,html,js,txt,bak
```

Use a custom wordlist:

```bash
dirsearch -u <target> -w /path/to/wordlist.txt
```

## Common flags

| Flag | Description |
|------|-------------|
| `-u <url>` | Target URL |
| `-e <exts>` | Extensions to scan (comma-separated) |
| `-w <file>` | Custom wordlist |
| `-t <threads>` | Number of threads |
| `-r` | Follow redirects |
| `-x <codes>` | Exclude status codes |
| `-o <file>` | Output file |
| `--json-report` | Output in JSON format |

## Safety

- Only scan targets you own or have explicit permission to test.
- High thread counts may overwhelm the target server; start with conservative settings.
