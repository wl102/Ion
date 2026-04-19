---
name: nmap
description: Network mapper for discovering hosts and services on a computer network. Use when you need to scan ports, discover live hosts, identify running services, or map network topology.
compatibility: Requires nmap to be installed on the system.
metadata:
  category: reconnaissance
  tool: nmap
---

# Nmap Skill

## When to use this skill

Use this skill when the task involves:
- Port scanning (TCP/UDP)
- Host discovery
- Service version detection
- OS fingerprinting
- Network topology mapping

## Basic usage

Scan a single target with service detection:

```bash
nmap -sV <target>
```

Scan all ports on a target:

```bash
nmap -p- -sV <target>
```

Stealth SYN scan (requires root):

```bash
sudo nmap -sS -sV <target>
```

## Common flags

| Flag | Description |
|------|-------------|
| `-sV` | Detect service versions |
| `-p <range>` | Scan specific ports (e.g., `-p 80,443` or `-p 1-65535`) |
| `-sS` | TCP SYN scan (stealth, requires root) |
| `-sT` | TCP connect scan |
| `-sU` | UDP scan |
| `-O` | OS detection |
| `-A` | Aggressive scan (OS + version + script + traceroute) |
| `-T<0-5>` | Timing template (0=paranoid, 5=insane) |
| `-Pn` | Skip host discovery, treat all hosts as up |

## Safety

- Only scan targets you have explicit authorization to scan.
- Be aware that aggressive scans may be logged by IDS/IPS.
- Use `-T2` or `-T3` for less noisy scans.
