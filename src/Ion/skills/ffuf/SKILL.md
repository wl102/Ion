---
name: ffuf
description: Fast web fuzzer for discovering resources, directories, virtual hosts, and parameters. Use when you need to fuzz URLs, headers, POST data, or virtual hosts with a wordlist.
compatibility: Requires ffuf to be installed on the system.
metadata:
  category: reconnaissance
  tool: ffuf
---

# FFUF Skill

## When to use this skill

Use this skill when the task involves:
- Fuzzing URL paths for hidden endpoints
- Discovering virtual hosts (VHost fuzzing)
- Fuzzing GET/POST parameters
- Directory brute-forcing with advanced filtering

## Basic usage

Fuzz URL paths:

```bash
ffuf -u http://<target>/FUZZ -w /usr/share/wordlists/dirb/common.txt
```

Fuzz virtual hosts:

```bash
ffuf -u http://<target>/ -H "Host: FUZZ.<target>" -w subdomains.txt
```

Fuzz POST parameters:

```bash
ffuf -u http://<target>/login -X POST -d "username=admin&password=FUZZ" -w passwords.txt
```

## Common flags

| Flag | Description |
|------|-------------|
| `-u <url>` | Target URL with FUZZ keyword |
| `-w <file>` | Wordlist file |
| `-X <method>` | HTTP method (GET, POST, etc.) |
| `-d <data>` | POST data with FUZZ keyword |
| `-H <header>` | Custom header with FUZZ keyword |
| `-mc <codes>` | Match status codes |
| `-fs <size>` | Filter by response size |
| `-t <threads>` | Number of threads |
| `-o <file>` | Output file |
| `-of <format>` | Output format (json, csv, etc.) |

## Safety

- Only fuzz targets you own or have explicit permission to test.
- Be mindful of rate limits; use `-t` to control concurrency.
