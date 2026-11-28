SysPulse: Windows PC Health & Utility CLI

Build Latest release Downloads Show Image Show Image

A lightweight, open-source Windows diagnostic and maintenance tool built in Python. One command gives your PC a health score from 0 to 100, tells you what is costing you points, and exports a report you can read, parse or screenshot.

<!-- Add a demo GIF here: ![SysPulse demo](docs/demo.gif) -->
What's new in v2.1
PC Health Score (0-100) with a letter grade and a list of what is costing you points
Shareable Health Card: a screenshot-friendly HTML card (no hostname or IP addresses on it)
Scan history and trends: every scan is saved locally, so you can see if your PC is getting better or worse
Live dashboard: auto-updating CPU, RAM, disk and network view
Offline virus check: drives Windows Defender with its local signatures, detect-only by default
Startup program inspector: see what slows down your boot
Network check: local/public IP and ping to 1.1.1.1 and 8.8.8.8
Battery health: wear level plus Windows' own powercfg report
Large file finder: top 10 biggest files in Downloads, C:\Users or any folder
Windows Update and system file checks: pending updates, DISM /CheckHealth, sfc /verifyonly (read-only)
Export as TXT, JSON, HTML or Card
CLI flags for automation (Task Scheduler friendly) and color-coded output
Download (no Python needed)
Get syspulse.exe from the latest release.
Double-click it for the interactive menu, or run it from a terminal with flags (below).
Verify your download

Each release includes a syspulse.exe.sha256 file, and the exe is built by GitHub Actions straight from this source code. Check it yourself:

powershell
Get-FileHash .\syspulse.exe -Algorithm SHA256

The exe is not code-signed, so Windows SmartScreen or your antivirus may show a warning. You can read every line of the source here, or run from source instead:

powershell
pip install -r requirements.txt
python main.py
Usage

Run with no flags for the interactive menu, or use flags for automation:

Flag	What it does
--scan	Full health scan and report export
--format txt|json|html|card|all	Report format for --scan (default txt)
--no-net	Privacy mode for --scan: no public-IP lookup, no pings
--live	Live dashboard (Ctrl+C to exit)
--history	Past scan scores and trends
--startup	List startup programs
--network	Local/public IP and DNS ping latency
--battery	Battery wear and powercfg report
--large-files [PATH]	10 largest files (default: Downloads)
--updates	Pending Windows updates
--integrity	DISM /CheckHealth and sfc /verifyonly (needs Administrator)
--virus-scan [quick|full|PATH]	Offline Defender scan; exit code 2 = threats found
--remediate	Let Defender remove or quarantine threats found by --virus-scan
--clean	Delete loose files in %TEMP% (no prompt)
--flush-dns	Flush the Windows DNS cache
--serious	Turn off the playful one-liners
--no-color	Plain output, good for logs

Example: a daily report with Task Scheduler:

powershell
syspulse.exe --scan --format html --no-color
How the Health Score works

The score starts at 100. Each factor can only cost a capped number of points, so one bad reading never zeroes everything:

Factor	Max points lost
RAM usage (starts costing above 60%)	20
Disk usage (starts costing above 70%)	20
Driver errors	15
CPU load	10
Startup programs	10
Battery wear	10
Network latency / unreachable DNS	10

Grades: A 90+, B 80+, C 70+, D 60+, F below 60. CPU load is a single moment in time, so run the scan on a typical day for a fair number.

Privacy and trust
No telemetry, no accounts, no analytics. Reports and history stay on your PC (~/.syspulse/history.json and your Desktop).
The only network activity is the public-IP lookup (api.ipify.org) and pings to 1.1.1.1 and 8.8.8.8. Use --no-net to skip both during a scan.
The Health Card leaves out your PC name and IP addresses, so it is safe to screenshot.
The virus check only controls Windows Defender. SysPulse is not an antivirus and does not detect malware itself. Signatures are as current as your last Windows update.
The temp cleaner only deletes loose files directly inside %TEMP%, never subfolders. The large file finder never deletes anything.
Contributing

Ideas, bug reports and pull requests are welcome. Open an issue first for big changes.

License

MIT. See LICENSE.

If SysPulse helped you, a star on the repo helps other people find it.