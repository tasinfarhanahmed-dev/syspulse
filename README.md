# SysPulse — Windows PC Health & Utility CLI

![Build Status](https://github.com)
![Latest Release](https://shields.io)
![Downloads](https://shields.io)

A lightweight, open-source Windows diagnostic and maintenance tool built in Python.

## ✨ What's New in v2.0
* **Interactive Main Menu:** Choose between running a full scan, flushing DNS, or cleaning loose temp files.
* **Full PC Health & Network Report:** Checks CPU, RAM, C: drive space, system uptime, battery status, top memory apps, DNS latency, and driver errors—then exports a timestamped report to your Desktop.
* **One-Click DNS Cache Flush:** Clears stale Windows DNS records to fix laggy browsing.
* **Safe Temp File Cleaner:** Sweeps loose temporary files directly inside `%TEMP%` without touching app subfolders.

## 📥 Download for Windows (No Python Required)
👉 **[Download Latest SysPulse (`syspulse.exe`)](https://github.com)**

1. Download **`syspulse.exe`**.
2. Double-click to open the interactive menu.

> **Note on Windows SmartScreen:** Because `syspulse.exe` is newly compiled and unsigned, Edge or Windows Defender may show *"isn't commonly downloaded"*. Click **Keep anyway** / **More info → Run anyway**, or inspect `main.py` directly. All `.exe` releases are built automatically from this public code via GitHub Actions.

---

## 💻 Run from Source (For Developers)
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the tool:
   ```bash
   python main.py
   ```
