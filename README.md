# SysPulse — Windows PC Health & Diagnostic CLI

![Build Status](https://github.com)
![Latest Release](https://shields.io)
![Downloads](https://shields.io)

A lightweight, open-source Windows diagnostic tool built in Python to check CPU/RAM usage, top memory-consuming apps, DNS ping speed, and driver health.

## 📥 Download for Windows (No Python Required)
👉 **[Download SysPulse (`syspulse.exe`)](https://github.com)**

1. Download **`syspulse.exe`**.
2. Double-click to run a full scan—a timestamped report card will automatically save to your Desktop and open in Notepad.

> **Note on Windows SmartScreen:** Because `syspulse.exe` is newly released and unsigned, Edge or Windows Defender may show *"isn't commonly downloaded"*. Click **Keep anyway** / **More info → Run anyway**, or inspect `main.py` directly. `syspulse.exe` is compiled automatically from this public source code via GitHub Actions and has been submitted to Microsoft Security Intelligence.

---

## 💻 Run from Source (For Developers)
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the script:
   ```bash
   python main.py
   ```
