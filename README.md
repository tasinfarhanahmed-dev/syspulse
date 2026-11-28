# SysPulse

**A lightweight, open-source Windows PC health & utility CLI built in Python.**

[![Build](https://shields.io)]()
[![Latest Release](https://shields.io)]()
[![Downloads](https://shields.io)]()
[![License: MIT](https://shields.io)](LICENSE)

One command gives your PC a **0–100 Health Score**, breaks down exactly what is costing you points, and exports a clean report you can read, parse, or share.

---

## ✨ Features

* **PC Health Score (0–100):** Instant letter grade (`A`–`F`) with an itemized list of point deductions.
* **Shareable Health Card:** Screenshot-friendly HTML summary card with sensitive info (hostname, IP addresses) stripped out.
* **Scan History & Trends:** Automatically saves scans locally to track whether your PC's health is improving or degrading over time.
* **Live Dashboard:** Real-time, auto-updating terminal view of CPU, RAM, disk, and network metrics.
* **Offline Virus Check:** Triggers Windows Defender using local signatures (detect-only by default, with optional remediation).
* **System & Maintenance Utilities:**
  * **Startup Inspector:** Identify apps slowing down boot times.
  * **Network Diagnostics:** View local/public IPs and ping latency to `1.1.1.1` and `8.8.8.8`.
  * **Battery Health:** Check wear levels alongside Windows' native `powercfg` report.
  * **Large File Finder:** Locate the top 10 largest files in `Downloads`, `C:\Users`, or any custom path.
  * **OS Integrity & Updates:** Check pending Windows Updates and run read-only `DISM /CheckHealth` and `sfc /verifyonly`.
  * **Quick Cleanup:** Clear loose files in `%TEMP%` and flush the Windows DNS cache.
* **Automation-Ready:** Flexible CLI flags, exit codes, and plain-text output built for Task Scheduler and scripts.

---

## 📦 Installation

### Option 1: Standalone Executable (No Python Required)
1. Download `syspulse.exe` from the [Latest Release](../../releases/latest).
2. Double-click to launch the **interactive menu**, or run it from PowerShell/CMD with CLI flags.

#### Verify Your Download
Every release includes a `syspulse.exe.sha256` checksum generated directly by GitHub Actions. Verify the integrity of your download in PowerShell:

```powershell
Get-FileHash .\syspulse.exe -Algorithm SHA256
```

> **Note on SmartScreen:** Because `syspulse.exe` is not code-signed, Windows SmartScreen or your antivirus may display a warning. You can audit the full source code in this repository or run directly from Python below.

### Option 2: Run from Source
```powershell
git clone https://github.com
cd syspulse
pip install -r requirements.txt
python main.py
```

---

## 🚀 Usage

Run `syspulse.exe` with **no flags** to open the interactive menu, or pass flags directly for quick checks and automation:

### CLI Flags

| Flag | Description |
| :--- | :--- |
| `--scan` | Run a full health scan and export a report |
| `--format <type>` | Output format for `--scan`: `txt`, `json`, `html`, `card`, or `all` *(default: `txt`)* |
| `--no-net` | Privacy mode for `--scan` (skips public IP lookup and DNS pings) |
| `--live` | Open the live resource dashboard (`Ctrl+C` to exit) |
| `--history` | View past scan scores and health trends |
| `--startup` | List startup programs |
| `--network` | Check local/public IP and DNS ping latency |
| `--battery` | Display battery wear level and `powercfg` report |
| `--large-files [PATH]` | List the 10 largest files *(default: `Downloads`)* |
| `--updates` | Check for pending Windows updates |
| `--integrity` | Run `DISM /CheckHealth` and `sfc /verifyonly` *(requires Administrator)* |
| `--virus-scan [MODE]` | Offline Defender scan: `quick`, `full`, or `[PATH]` *(exit code `2` = threats found)* |
| `--remediate` | Allow Defender to quarantine/remove threats found during `--virus-scan` |
| `--clean` | Delete loose files in `%TEMP%` without prompting |
| `--flush-dns` | Flush the Windows DNS cache |
| `--serious` | Disable playful one-liners in output |
| `--no-color` | Output plain text without ANSI colors *(ideal for log files)* |

### Automation Example (Task Scheduler)
Generate a daily, uncolored HTML health report automatically:
```powershell
syspulse.exe --scan --format html --no-color
```

---

## 📊 How the Health Score Works

Your PC starts at **100 points**. Deductions are capped per category so a single spike never tanks your entire score:

| Factor | Max Points Lost | Notes |
| :--- | :---: | :--- |
| **RAM Usage** | `20` | Deductions begin above 60% usage |
| **Disk Usage** | `20` | Deductions begin above 70% usage |
| **Driver Errors** | `15` | Based on Windows device/driver status |
| **CPU Load** | `10` | Point-in-time snapshot; scan during typical workload |
| **Startup Programs** | `10` | Impact from enabled boot items |
| **Battery Wear** | `10` | Applies to laptops/devices with batteries |
| **Network Latency** | `10` | Ping latency or unreachable DNS (`1.1.1.1` / `8.8.8.8`) |

**Grading Scale:** `A` (90+) · `B` (80–89) · `C` (70–79) · `D` (60–69) · `F` (< 60)

---

## 🔒 Privacy & Safety Guarantees

* **Zero Telemetry:** No accounts, analytics, or background tracking.
* **Local Data Only:** Reports and scan history remain strictly on your machine (`~/.syspulse/history.json` and your Desktop).
* **Minimal Network Calls:** SysPulse only contacts `api.ipify.org` (public IP lookup) and pings `1.1.1.1` / `8.8.8.8`. Use `--no-net` to run completely offline.
* **Safe to Share:** The HTML Health Card omits your computer name and IP addresses.
* **Non-Destructive Defaults:**
  * `--virus-scan` only invokes Windows Defender's existing local engine/signatures in read-only detection mode unless `--remediate` is explicitly passed.
  * `--clean` only removes loose files directly inside `%TEMP%`—never subfolders.
  * `--large-files` is strictly read-only and never deletes anything.

---

## 🤝 Contributing & License

Contributions, bug reports, and feature ideas are welcome! Please open an issue first before submitting large changes.

Licensed under the [MIT License](LICENSE).

> ⭐ **Enjoying SysPulse?** Give the repository a star to help others discover it!
