---
name: race-condition
description: Race condition vulnerability detection and exploitation. Covers time-of-check to time-of-use (TOCTOU), limit bypass, coupon abuse, and multi-endpoint race chains. Use when state-dependent logic (credits, inventory, votes, transfers) exists or CTF challenge involves concurrent operations.
metadata:
  hermes:
    category: web-security
    tags: [race-condition, toctou, concurrency, limit-bypass, ctf]
platforms: [linux, macos, windows]
---

# Race Condition Skill

## When to Use

Activate this skill when:
- The target has state-dependent logic (account balance, inventory count, rate limits, vote counts)
- You observe "check then act" patterns (verify funds → deduct funds, check ownership → delete)
- CTF challenge involves "limited uses", "one-time coupon", "first N users", or "transfer" mechanics
- You want to bypass "once per user", "max 1 item", or "insufficient balance" restrictions

---

## Core Concepts

A race condition occurs when the **correctness of a computation depends on the relative timing of events**. In web applications, this typically means multiple requests arrive between a "check" and an "act", causing the act to execute multiple times based on a single favorable check.

### Classic Patterns

| Pattern | Check | Act | Exploit Goal |
|---------|-------|-----|--------------|
| **TOCTOU File** | `access(filename, W_OK)` | `write(filename, data)` | Overwrite file you shouldn't own |
| **Credit Deduction** | `if balance >= amount` | `balance -= amount; transfer()` | Withdraw more than balance |
| **Coupon Use** | `if !coupon.used` | `coupon.used = true; apply()` | Use same coupon N times |
| **Inventory Purchase** | `if stock > 0` | `stock -= 1; create_order()` | Buy item when stock = 0 |
| **Privilege Escalation** | `if user.is_admin` | `perform_admin_action()` | Degrade self to user mid-request |

---

## Detection Methodology

### Step 1: Identify State-Dependent Operations
Look for endpoints that:
- Modify a numeric counter (balance, credits, votes, likes)
- Apply one-time tokens or coupons
- Enforce ownership before deletion/modification
- Have "check-then-act" logic in source code or behavior

### Step 2: Single-Request Baseline
1. Record the initial state (e.g., balance = 100, coupon unused)
2. Send ONE legitimate request
3. Verify state changes correctly (balance = 90, coupon used)

### Step 3: Concurrent Burst Testing
Send N identical requests **simultaneously** (within milliseconds):
```python
import asyncio, aiohttp

async def fire(url, payload, count=30):
    async with aiohttp.ClientSession() as session:
        async def one():
            async with session.post(url, data=payload) as r:
                return await r.text()
        return await asyncio.gather(*[one() for _ in range(count)])
```

**Key observation**: If the final state differs from `initial - N * single_change`, a race exists.

### Step 4: Multi-Endpoint Race Chain (Advanced)
Some races span **multiple endpoints**:
1. `POST /transfer` — initiates transfer (deducts from A, pending to B)
2. `POST /confirm` — confirms transfer (credits B)

Race: Call `/confirm` multiple times before `/transfer` marks it as completed.

---

## Exploitation Patterns

### Pattern 1: Coupon/Token Reuse (Single-Endpoint)
```python
# Target: POST /apply-coupon  (one-time use, 10% discount)
# Exploit: 30 concurrent requests with same coupon code

async def race_coupon(session, url, coupon_code):
    payload = {"coupon": coupon_code}
    tasks = [session.post(url, data=payload) for _ in range(30)]
    responses = await asyncio.gather(*tasks)
    successes = [r for r in responses if "applied" in await r.text()]
    return len(successes)  # If > 1, race condition confirmed
```

### Pattern 2: Balance Overflow / Over-Withdrawal
```python
# Target: POST /withdraw  (balance = 100, withdraw = 30)
# Exploit: 10 concurrent withdraw requests

async def race_withdraw(session, url, amount):
    payload = {"amount": amount}
    tasks = [session.post(url, json=payload) for _ in range(10)]
    responses = await asyncio.gather(*tasks)
    # Check final balance: if negative or less than expected, race succeeded
```

### Pattern 3: Limit Bypass (Votes, Likes, API Quota)
```python
# Target: POST /vote  (max 1 vote per user per day)
# Exploit: Burst 50 votes at exactly 00:00:00 when daily reset occurs
# OR: Exploit check-cache vs act-database inconsistency
```

### Pattern 4: IDOR + Race Chain
```python
# Target:
#   1. POST /create-report  → returns report_id, sets owner = current_user
#   2. POST /delete-report  → deletes if owner == current_user
# Exploit:
#   - Create report
#   - Immediately fire 20 delete requests with incremented report_ids
#   - Some may hit reports created by other users in the same microsecond
```

---

## CTF-Specific Shortcuts

### Quick Win Checklist
1. **Check for numeric state** — any counter, balance, or limit is a race candidate
2. **Look for "first N" or "limited" language** in challenge description
3. **Try 20-50 concurrent requests** — CTF race windows are often wide (no DB transactions)
4. **Race at state transitions** — midnight reset, session creation, coupon generation
5. **Combine with other bugs** — Race + IDOR = delete other users' data

### Common CTF Race Scenarios
| Challenge Type | Vulnerable Pattern | Exploit |
|----------------|-------------------|---------|
| Banking / Wallet | Check balance → Deduct | Over-withdraw |
| Shop / Inventory | Check stock → Deduct | Buy sold-out item |
| Coupon / Promo | Check used → Mark used | Reuse coupon |
| Vote / Poll | Check voted → Record vote | Multiple votes |
| File Upload | Check extension → Write file | TOCTOU extension swap |
| Transfer | Check ownership → Transfer | Transfer same item twice |

### Turbo Intruder Alternative (Python)
CTF environments rarely have Turbo Intruder. Use Python with `asyncio` and `aiohttp`:
```python
import asyncio, aiohttp, time

async def turbo_race(url, payload, connections=50):
    async with aiohttp.ClientSession() as session:
        # Warm-up: establish connections
        await session.get(url)
        
        async def single():
            async with session.post(url, data=payload) as resp:
                return resp.status, await resp.text()
        
        # Fire as simultaneously as possible
        start = time.time()
        results = await asyncio.gather(*[single() for _ in range(connections)])
        elapsed = time.time() - start
        
        # Analyze results
        successes = sum(1 for status, _ in results if status == 200)
        return {"successes": successes, "elapsed": elapsed, "results": results}
```

---

## Tool Recommendations

### Python-Based Race Tools
- **`python_exec` with `asyncio` + `aiohttp`** — Primary method. Full control over timing and concurrency.
- **`requests` + `threading`** — Simpler but less concurrent than async; use 50+ threads for best results.

### Key Parameters
| Parameter | Recommendation | Rationale |
|-----------|---------------|-----------|
| **Concurrency** | 20–100 requests | CTF apps often have wide race windows |
| **Connection reuse** | `Connection: keep-alive` | Reduces TCP handshake overhead |
| **Timing precision** | Fire all requests in < 10ms | Use `asyncio.gather` with pre-warmed connections |
| **Retries** | 3–5 rounds | Race conditions are probabilistic |

---

## Pitfalls

- **False negatives from low concurrency**: 2–3 requests rarely trigger races. Use 20+.
- **Rate limiting**: Some CTFs throttle IP-level requests. Use `X-Forwarded-For` rotation if allowed.
- **Database transactions**: Well-written apps use `SELECT FOR UPDATE` or atomic increments. If 100 requests never trigger a race, pivot to other bugs.
- **Session serialization**: PHP default session handler serializes requests per session. Use multiple sessions or session-less endpoints.
- **Caching layers**: If the "check" reads from cache and "act" writes to DB, the race window may be **seconds** wide — exploit aggressively.

## Verification Checklist

- [ ] Identified state-dependent check-then-act logic
- [ ] Established single-request baseline
- [ ] Fired 20+ concurrent requests and observed unexpected state
- [ ] Reproduced the race condition at least 2 times
- [ ] Calculated final state to confirm exploitation succeeded
- [ ] Documented the exact timing and concurrency required
