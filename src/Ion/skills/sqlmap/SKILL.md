---
name: sqlmap
description: Automatic SQL injection and database takeover tool. Use when you suspect a web parameter is vulnerable to SQL injection and need to test, exploit, or enumerate the database.
compatibility: Requires sqlmap to be installed on the system.
metadata:
  category: exploitation
  tool: sqlmap
---

# SQLMap Skill

## When to use this skill

Use this skill when the task involves:
- Testing for SQL injection vulnerabilities
- Extracting database schema information
- Dumping database contents
- Bypassing WAFs for SQLi testing

## Basic usage

Test a URL parameter for SQL injection:

```bash
sqlmap -u "<target>" --batch
```

Enumerate databases:

```bash
sqlmap -u "<target>" --dbs --batch
```

Dump a specific database:

```bash
sqlmap -u "<target>" -D <database> --dump --batch
```

Test with POST data:

```bash
sqlmap -u "<target>" --data="param1=value1&param2=value2" --batch
```

## Common flags

| Flag | Description |
|------|-------------|
| `-u <url>` | Target URL |
| `--batch` | Non-interactive mode (use defaults) |
| `--dbs` | Enumerate databases |
| `--tables` | Enumerate tables |
| `--columns` | Enumerate columns |
| `--dump` | Dump table entries |
| `-D <db>` | Specify database |
| `-T <table>` | Specify table |
| `-C <col>` | Specify column |
| `--level <1-5>` | Test level (higher = more tests) |
| `--risk <1-3>` | Risk level (higher = more dangerous) |
| `--tamper <script>` | Use tamper script to evade WAF |

## Safety

- SQLMap can be destructive. Always run with `--batch` in automated contexts.
- Never use `--os-shell`, `--os-pwn`, or other takeover features without explicit authorization.
- High `--risk` and `--level` values can cause data loss or service disruption.
