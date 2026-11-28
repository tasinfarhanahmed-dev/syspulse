from __future__ import annotations

import argparse
import ctypes
import heapq
import html
import json
import os
import platform
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    import psutil
    from rich import box
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:
    sys.exit("Missing dependencies. Run: pip install -r requirements.txt")

try:
    import winreg  # Windows only
except ImportError:
    winreg = None

VERSION = "2.1.0"

WARN_PCT = 85          # yellow at/above this
CRIT_PCT = 95          # red at/above this
WEAR_WARN = 40         # battery wear % thresholds
WEAR_CRIT = 60
PING_WARN_MS = 100
PING_CRIT_MS = 250

DNS_TARGETS = {"Cloudflare": "1.1.1.1", "Google": "8.8.8.8"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REPARSE_POINT = 0x400

REPO_URL = "https://github.com/tasinfarhanahmed-dev/SysPulse"  # change if your repo name differs
HISTORY_FILE = Path.home() / ".syspulse" / "history.json"
GRADES = [(90, "A", "Excellent"), (80, "B", "Good"), (70, "C", "Fair"),
          (60, "D", "Needs attention"), (0, "F", "Critical")]
SERIOUS = False  # --serious turns off the playful one-liners

console = Console()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command quietly and return (returncode, stdout)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace",
            timeout=timeout, creationflags=NO_WINDOW,
        )
        return r.returncode, (r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def powershell(script: str, timeout: int = 30) -> tuple[int, str]:
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def level(pct: float) -> str:
    if pct >= CRIT_PCT:
        return "red"
    if pct >= WARN_PCT:
        return "yellow"
    return "green"


def colorize(pct: float, text: str | None = None) -> str:
    return f"[{level(pct)}]{text or f'{pct:.1f}%'}[/]"


def gb(n: int) -> float:
    return round(n / (1024 ** 3), 1)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def output_dir() -> Path:
    """Desktop if it exists (incl. OneDrive-redirected), else the home folder."""
    home = Path.home()
    candidates = [home / "Desktop"]
    onedrive = os.environ.get("OneDrive")
    if onedrive:
        candidates.append(Path(onedrive) / "Desktop")
    for c in candidates:
        if c.is_dir():
            return c
    return home


# --------------------------------------------------------------------------
# Startup program inspector
# --------------------------------------------------------------------------
def get_startup_items() -> list[dict]:
    """Programs set to launch at logon via Run keys and Startup folders."""
    items: list[dict] = []

    if winreg:
        run_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        keys = [
            (winreg.HKEY_CURRENT_USER, run_path, "Registry (current user)"),
            (winreg.HKEY_LOCAL_MACHINE, run_path, "Registry (all users)"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run",
             "Registry (all users, 32-bit)"),
        ]
        for hive, path, source in keys:
            try:
                with winreg.OpenKey(hive, path) as key:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, i)
                        except OSError:
                            break
                        items.append({"name": name, "command": str(value), "source": source})
                        i += 1
            except OSError:
                continue

    folders = [
        (Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup",
         "Startup folder (current user)"),
        (Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs/StartUp",
         "Startup folder (all users)"),
    ]
    for folder, source in folders:
        try:
            if folder.is_dir():
                for f in folder.iterdir():
                    if f.name.lower() != "desktop.ini":
                        items.append({"name": f.stem, "command": str(f), "source": source})
        except OSError:
            continue
    return items


def show_startup() -> None:
    items = get_startup_items()
    console.rule("[bold cyan]Startup Program Inspector")
    if not items:
        console.print("[green]No startup entries found in Run keys or Startup folders.[/]")
        return
    t = Table(box=box.SIMPLE_HEAD, show_lines=False)
    t.add_column("Name", style="bold")
    t.add_column("Command / Path", overflow="fold")
    t.add_column("Source", style="dim")
    for it in items:
        t.add_row(escape(it["name"]), escape(it["command"]), it["source"])
    console.print(t)
    color = "yellow" if len(items) > 10 else "green"
    console.print(f"[{color}]{len(items)} startup entries.[/] "
                  "Disable unwanted ones in Task Manager > Startup apps.")


# --------------------------------------------------------------------------
# Network diagnostics
# --------------------------------------------------------------------------
def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packets are actually sent
            return s.getsockname()[0]
    except OSError:
        return "unavailable"


def public_ip() -> str:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                ip = resp.read().decode().strip()
            if re.fullmatch(r"[0-9a-fA-F.:]+", ip):
                return ip
        except Exception:
            continue
    return "unavailable"


def ping_ms(host: str, count: int = 3) -> float | None:
    """Average ICMP latency; falls back to a TCP connect to port 53."""
    code, out = run(["ping", "-n", str(count), host], timeout=count * 5 + 5)
    if code == 0:
        vals = re.findall(r"=\s*(\d+)\s*ms", out)
        if vals:
            return float(vals[-1])  # last match = "Average = Xms"
    try:
        start = time.perf_counter()
        with socket.create_connection((host, 53), timeout=3):
            pass
        return round((time.perf_counter() - start) * 1000, 1)
    except OSError:
        return None


def get_network(skip: bool = False) -> dict:
    if skip:  # --no-net: no public-IP lookup and no pings
        return {"local_ip": local_ip(), "public_ip": "skipped (--no-net)", "latency_ms": {}}
    return {
        "local_ip": local_ip(),
        "public_ip": public_ip(),
        "latency_ms": {name: ping_ms(ip) for name, ip in DNS_TARGETS.items()},
    }


def latency_text(ms: float | None) -> str:
    if ms is None:
        return "[red]timeout[/]"
    color = "red" if ms >= PING_CRIT_MS else "yellow" if ms >= PING_WARN_MS else "green"
    return f"[{color}]{ms:g} ms[/]"


def show_network() -> None:
    console.rule("[bold cyan]Network Diagnostics")
    with console.status("Checking network..."):
        net = get_network()
    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column(style="bold")
    t.add_column()
    t.add_row("Local IP", net["local_ip"])
    t.add_row("Public IP", net["public_ip"])
    for name, ms in net["latency_ms"].items():
        t.add_row(f"Ping {name} ({DNS_TARGETS[name]})", latency_text(ms))
    console.print(t)


# --------------------------------------------------------------------------
# Battery
# --------------------------------------------------------------------------
def get_battery() -> dict | None:
    b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if b is None:
        return None
    info = {
        "percent": round(b.percent, 1),
        "plugged_in": bool(b.power_plugged),
        "design_mwh": None,
        "full_mwh": None,
        "wear_percent": None,
    }
    script = (
        "$d=(Get-CimInstance -Namespace root\\wmi -ClassName BatteryStaticData "
        "-ErrorAction SilentlyContinue | Select-Object -First 1).DesignedCapacity;"
        "$f=(Get-CimInstance -Namespace root\\wmi -ClassName BatteryFullChargedCapacity "
        "-ErrorAction SilentlyContinue | Select-Object -First 1).FullChargedCapacity;"
        '"$d,$f"'
    )
    code, out = powershell(script, timeout=20)
    if code == 0 and "," in out:
        try:
            design, full = (int(x) for x in out.split(",")[:2])
            if design > 0 and full > 0:
                info["design_mwh"], info["full_mwh"] = design, full
                info["wear_percent"] = round(max(0.0, (1 - full / design) * 100), 1)
        except ValueError:
            pass
    return info


def battery_text(b: dict) -> str:
    s = f"{b['percent']}% ({'plugged in' if b['plugged_in'] else 'on battery'})"
    if b["wear_percent"] is not None:
        s += f", wear {b['wear_percent']}% ({b['full_mwh']} / {b['design_mwh']} mWh)"
    return s


def show_battery() -> None:
    console.rule("[bold cyan]Battery Health")
    b = get_battery()
    if b is None:
        console.print("[yellow]No battery detected (desktop PC?).[/]")
        return
    console.print(f"Charge: {b['percent']}% ({'plugged in' if b['plugged_in'] else 'on battery'})")
    if b["wear_percent"] is None:
        console.print("[yellow]Could not read design/full-charge capacity from Windows.[/]")
    else:
        health = 100 - b["wear_percent"]
        color = "red" if b["wear_percent"] >= WEAR_CRIT else "yellow" if b["wear_percent"] >= WEAR_WARN else "green"
        console.print(f"Design capacity: {b['design_mwh']} mWh | Full charge: {b['full_mwh']} mWh")
        console.print(f"Battery health: [{color}]{health:.1f}%[/] (wear {b['wear_percent']}%)")
    path = output_dir() / f"SysPulse_BatteryReport_{datetime.now():%Y%m%d_%H%M%S}.html"
    code, _ = run(["powercfg", "/batteryreport", "/output", str(path)], timeout=60)
    if code == 0 and path.exists():
        console.print(f"Windows battery report saved to [cyan]{escape(str(path))}[/]")
    else:
        console.print("[yellow]powercfg battery report could not be generated.[/]")


# --------------------------------------------------------------------------
# Full health scan
# --------------------------------------------------------------------------
def top_memory_apps(n: int = 5) -> list[dict]:
    totals: dict[str, int] = {}
    for p in psutil.process_iter(["name", "memory_info"]):
        mi = p.info.get("memory_info")
        if mi:
            name = p.info.get("name") or "unknown"
            totals[name] = totals.get(name, 0) + mi.rss
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return [{"name": k, "memory_mb": round(v / (1024 ** 2))} for k, v in ranked]


def driver_errors() -> list[str]:
    script = ("Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } "
              "| ForEach-Object { $_.Name }")
    code, out = powershell(script, timeout=45)
    return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []


def collect_report(skip_net: bool = False) -> dict:
    vm = psutil.virtual_memory()
    drive = os.environ.get("SystemDrive", "C:")
    disk = psutil.disk_usage(drive + "\\")
    up = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
    cpu = psutil.cpu_percent(interval=1)

    report = {
        "syspulse_version": VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": {"percent": cpu, "cores": psutil.cpu_count()},
        "memory": {"percent": vm.percent, "used_gb": gb(vm.used), "total_gb": gb(vm.total)},
        "disk": {"drive": drive, "percent": disk.percent, "used_gb": gb(disk.used),
                 "free_gb": gb(disk.free), "total_gb": gb(disk.total)},
        "uptime": f"{up.days}d {up.seconds // 3600}h {(up.seconds // 60) % 60}m",
        "battery": get_battery(),
        "top_memory_apps": top_memory_apps(),
        "network": get_network(skip_net),
        "driver_errors": driver_errors(),
        "startup_items": get_startup_items(),
    }

    w: list[str] = []
    for label, pct in (("CPU", cpu), ("RAM", vm.percent), (f"Disk {drive}", disk.percent)):
        if pct >= WARN_PCT:
            w.append(f"{label} usage is high ({pct:.1f}%).")
    b = report["battery"]
    if b and b["wear_percent"] is not None and b["wear_percent"] >= WEAR_WARN:
        w.append(f"Battery has lost {b['wear_percent']}% of its design capacity.")
    if report["driver_errors"]:
        w.append(f"{len(report['driver_errors'])} device(s) report driver errors.")
    for name, ms in report["network"]["latency_ms"].items():
        if ms is None:
            w.append(f"No response from {name} DNS ({DNS_TARGETS[name]}).")
        elif ms >= PING_WARN_MS:
            w.append(f"High latency to {name} DNS ({ms:g} ms).")
    if len(report["startup_items"]) > 10:
        w.append(f"{len(report['startup_items'])} startup entries may slow boot time.")
    report["warnings"] = w
    report["score"] = health_score(report)
    report["quip"] = quip(report)
    return report


def print_score(r: dict) -> None:
    s = r["score"]
    v = s["value"]
    color = "green" if v >= 80 else "yellow" if v >= 60 else "red"
    console.print(f"  Health Score: [bold {color}]{v}/100[/]  ([{color}]{s['grade']}[/] - {s['label']})")
    if r.get("quip"):
        console.print(f"  [italic]{escape(r['quip'])}[/]")
    if s["breakdown"]:
        console.print("  [dim]Costing you points: " + ", ".join(
            f"{escape(x['item'])} (-{x['points_lost']})" for x in s["breakdown"][:3]) + "[/]")
    for line in r.get("trend", []):
        console.print(f"  [dim]{escape(line)}[/]")


def print_report(r: dict) -> None:
    console.print(Panel.fit(
        f"[bold]SysPulse {VERSION}[/]  |  {escape(r['hostname'])}  |  {r['generated_at']}",
        border_style="cyan"))
    print_score(r)
    t = Table(box=box.SIMPLE, show_header=False)
    t.add_column(style="bold")
    t.add_column()
    c, m, d = r["cpu"], r["memory"], r["disk"]
    t.add_row("CPU", f"{colorize(c['percent'])} ({c['cores']} logical cores)")
    t.add_row("RAM", f"{colorize(m['percent'])} ({m['used_gb']} / {m['total_gb']} GB)")
    t.add_row(f"Disk {d['drive']}",
              f"{colorize(d['percent'])} ({d['free_gb']} GB free of {d['total_gb']} GB)")
    t.add_row("Uptime", r["uptime"])
    if r["battery"]:
        t.add_row("Battery", battery_text(r["battery"]))
    n = r["network"]
    t.add_row("Local IP", n["local_ip"])
    t.add_row("Public IP", n["public_ip"])
    for name, ms in n["latency_ms"].items():
        t.add_row(f"Ping {name}", latency_text(ms))
    de = len(r["driver_errors"])
    t.add_row("Driver errors", f"[{'red' if de else 'green'}]{de}[/]")
    si = len(r["startup_items"])
    t.add_row("Startup items", f"[{'yellow' if si > 10 else 'green'}]{si}[/]")
    console.print(t)

    mt = Table(title="Top memory apps", box=box.SIMPLE_HEAD)
    mt.add_column("App")
    mt.add_column("Memory", justify="right")
    for app in r["top_memory_apps"]:
        mt.add_row(escape(app["name"]), f"{app['memory_mb']} MB")
    console.print(mt)

    if r["warnings"]:
        console.print(Panel("\n".join(f"[yellow]![/] {escape(x)}" for x in r["warnings"]),
                            title="Warnings", border_style="yellow"))
    else:
        console.print("[green]No warnings. System looks healthy.[/]")


# --------------------------------------------------------------------------
# Report export (txt / json / html)
# --------------------------------------------------------------------------
def summary_rows(r: dict) -> list[tuple[str, str]]:
    c, m, d, n = r["cpu"], r["memory"], r["disk"], r["network"]
    sc = r["score"]
    rows = [
        ("Health score", f"{sc['value']}/100 (Grade {sc['grade']} - {sc['label']})"),
        ("CPU", f"{c['percent']}% ({c['cores']} logical cores)"),
        ("RAM", f"{m['percent']}% ({m['used_gb']} / {m['total_gb']} GB)"),
        (f"Disk {d['drive']}", f"{d['percent']}% used ({d['free_gb']} GB free of {d['total_gb']} GB)"),
        ("Uptime", r["uptime"]),
    ]
    if r["battery"]:
        rows.append(("Battery", battery_text(r["battery"])))
    rows += [("Local IP", n["local_ip"]), ("Public IP", n["public_ip"])]
    for name, ms in n["latency_ms"].items():
        rows.append((f"Ping {name}", f"{ms:g} ms" if ms is not None else "timeout"))
    rows += [("Driver errors", str(len(r["driver_errors"]))),
             ("Startup items", str(len(r["startup_items"])))]
    return rows


def render_text(r: dict) -> str:
    lines = [f"SysPulse v{VERSION} - PC Health Report",
             f"Generated: {r['generated_at']}  |  Host: {r['hostname']}",
             f"OS: {r['os']}", "=" * 60]
    lines += [f"{k:<16}{v}" for k, v in summary_rows(r)]
    lines += ["", "Top memory apps:"]
    lines += [f"  {a['name']:<30}{a['memory_mb']} MB" for a in r["top_memory_apps"]]
    if r["driver_errors"]:
        lines += ["", "Devices with driver errors:"] + [f"  - {x}" for x in r["driver_errors"]]
    if r["startup_items"]:
        lines += ["", "Startup items:"]
        lines += [f"  - {i['name']}  [{i['source']}]" for i in r["startup_items"]]
    if r.get("trend"):
        lines += ["", "Since last scan:"] + [f"  {x}" for x in r["trend"]]
    lines += ["", "Warnings:"]
    lines += [f"  ! {x}" for x in r["warnings"]] or ["  None"]
    return "\n".join(lines) + "\n"


def render_html(r: dict) -> str:
    e = html.escape

    def table(rows, head=None):
        h = "".join(f"<th>{e(x)}</th>" for x in head) if head else ""
        body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table>{f'<tr>{h}</tr>' if h else ''}{body}</table>"

    warnings = "".join(f"<li>{e(w)}</li>" for w in r["warnings"]) or "<li class='ok'>None</li>"
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SysPulse Report - {e(r['hostname'])}</title>
<style>
  body {{ font-family: Segoe UI, Arial, sans-serif; max-width: 820px; margin: 2rem auto; padding: 0 1rem; color: #1f2328; background: #fff; }}
  h1 {{ margin-bottom: .2rem; }} .meta {{ color: #656d76; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
  td, th {{ text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #d0d7de; }}
  .warn li {{ color: #9a6700; }} .ok {{ color: #1a7f37; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #e6edf3; }} td, th {{ border-color: #30363d; }} .meta {{ color: #8b949e; }}
    .warn li {{ color: #e3b341; }} .ok {{ color: #3fb950; }}
  }}
</style></head><body>
<h1>SysPulse PC Health Report</h1>
<div class="meta">{e(r['hostname'])} &middot; {e(r['generated_at'])} &middot; {e(r['os'])} &middot; v{VERSION}</div>
<h2>Summary</h2>{table(summary_rows(r))}
<h2>Top memory apps</h2>{table([(a['name'], f"{a['memory_mb']} MB") for a in r['top_memory_apps']], ['App', 'Memory'])}
<h2>Startup items</h2>{table([(i['name'], i['source'], i['command']) for i in r['startup_items']], ['Name', 'Source', 'Command']) if r['startup_items'] else '<p>None found.</p>'}
<h2>Driver errors</h2>{('<ul>' + ''.join(f'<li>{e(x)}</li>' for x in r['driver_errors']) + '</ul>') if r['driver_errors'] else '<p class="ok">None</p>'}
<h2>Warnings</h2><ul class="warn">{warnings}</ul>
</body></html>
"""


def save_report(r: dict, fmt: str) -> list[Path]:
    renderers = {
        "txt": render_text,
        "json": lambda x: json.dumps(x, indent=2, ensure_ascii=False),
        "html": render_html,
        "card": render_card,
    }
    formats = list(renderers) if fmt == "all" else [fmt]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = output_dir()
    paths = []
    for f in formats:
        p = out / (f"SysPulse_Card_{stamp}.html" if f == "card" else f"SysPulse_Report_{stamp}.{f}")
        p.write_text(renderers[f](r), encoding="utf-8")
        paths.append(p)
    return paths


def run_scan(fmt: str = "txt", skip_net: bool = False) -> None:
    console.rule("[bold cyan]Full PC Health Scan")
    with console.status("Scanning system (this takes a few seconds)..."):
        report = collect_report(skip_net)
    history = load_history()
    report["trend"] = compute_trend(history, report)
    print_report(report)
    history.append(history_entry(report))
    save_history(history)
    try:
        for p in save_report(report, fmt):
            console.print(f"Report saved to [cyan]{escape(str(p))}[/]")
    except OSError as exc:
        console.print(f"[red]Could not save report: {escape(str(exc))}[/]")


# --------------------------------------------------------------------------
# Maintenance: DNS flush, temp cleaner, large files
# --------------------------------------------------------------------------
def flush_dns() -> None:
    code, out = run(["ipconfig", "/flushdns"])
    if code == 0:
        console.print("[green]DNS resolver cache flushed.[/]")
    else:
        console.print("[red]Could not flush DNS cache.[/] Try an elevated (Administrator) terminal.")
        if out:
            console.print(escape(out))


def clean_temp(confirm: bool = True) -> None:
    """Delete loose files directly inside %TEMP% (subfolders are left alone)."""
    temp = Path(tempfile.gettempdir())
    try:
        files = [f for f in temp.iterdir() if f.is_file() and not f.is_symlink()]
    except OSError as exc:
        console.print(f"[red]Cannot read {escape(str(temp))}: {escape(str(exc))}[/]")
        return
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    console.print(f"Found {len(files)} loose files in [cyan]{escape(str(temp))}[/] ({human_size(total)}).")
    if not files:
        return
    if confirm and not Confirm.ask("Delete them?", default=False):
        console.print("Cancelled.")
        return
    freed = deleted = skipped = 0
    for f in files:
        try:
            size = f.stat().st_size
            f.unlink()
            freed += size
            deleted += 1
        except OSError:
            skipped += 1  # in use or protected
    console.print(f"[green]Deleted {deleted} files, freed {human_size(freed)}.[/] "
                  f"Skipped {skipped} (in use or protected).")


def _is_reparse(path: str) -> bool:
    try:
        return bool(os.lstat(path).st_file_attributes & REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def find_large_files(root: str, top_n: int = 10) -> tuple[list[tuple[int, str]], int]:
    heap: list[tuple[int, str]] = []
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        # skip junctions/symlinks to avoid loops and double counting
        dirnames[:] = [d for d in dirnames if not _is_reparse(os.path.join(dirpath, d))]
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                if os.path.islink(fp):
                    continue
                size = os.path.getsize(fp)
            except OSError:
                continue
            scanned += 1
            if len(heap) < top_n:
                heapq.heappush(heap, (size, fp))
            elif size > heap[0][0]:
                heapq.heapreplace(heap, (size, fp))
    return sorted(heap, reverse=True), scanned


def show_large_files(root: str | None = None) -> None:
    root = root or str(Path.home() / "Downloads")
    console.rule("[bold cyan]Large File Finder")
    if not os.path.isdir(root):
        console.print(f"[red]Folder not found:[/] {escape(root)}")
        return
    with console.status(f"Scanning {root} ..."):
        results, scanned = find_large_files(root)
    if not results:
        console.print("No files found.")
        return
    t = Table(title=f"Top {len(results)} largest files in {escape(root)}", box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right")
    t.add_column("Size", justify="right")
    t.add_column("Path", overflow="fold")
    for i, (size, path) in enumerate(results, 1):
        t.add_row(str(i), human_size(size), escape(path))
    console.print(t)
    console.print(f"Scanned {scanned:,} files. SysPulse never deletes these; review them yourself.")


# --------------------------------------------------------------------------
# Windows Update + system file checks (read-only)
# --------------------------------------------------------------------------
def show_pending_updates() -> None:
    console.rule("[bold cyan]Pending Windows Updates")
    script = ("$s = New-Object -ComObject Microsoft.Update.Session;"
              "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0');"
              "$r.Updates | ForEach-Object { $_.Title }")
    with console.status("Asking Windows Update (can take up to a minute)..."):
        code, out = powershell(script, timeout=240)
    if code != 0:
        console.print("[yellow]Could not query Windows Update.[/]")
        return
    titles = [x.strip() for x in out.splitlines() if x.strip()]
    if not titles:
        console.print("[green]No pending updates.[/]")
        return
    console.print(f"[yellow]{len(titles)} pending update(s):[/]")
    for title in titles:
        console.print(f"  - {escape(title)}")


def run_integrity_checks(run_sfc: bool) -> None:
    console.rule("[bold cyan]System File Health (read-only)")
    if not is_admin():
        console.print("[yellow]DISM and SFC need an elevated terminal. "
                      "Re-run SysPulse as Administrator to use this.[/]")
        return
    console.print("[bold]DISM /CheckHealth[/]")
    subprocess.run(["DISM", "/Online", "/Cleanup-Image", "/CheckHealth"])
    if run_sfc:
        console.print("\n[bold]sfc /verifyonly[/] (can take several minutes)")
        subprocess.run(["sfc", "/verifyonly"])


# --------------------------------------------------------------------------
# Health score, history, live dashboard & shareable card
# --------------------------------------------------------------------------
def _ramp(value: float | None, start: float, end: float, max_pen: float) -> float:
    """0 penalty at/below `start`, `max_pen` at/above `end`, linear in between."""
    if value is None:
        return 0.0
    return max_pen * min(1.0, max(0.0, (value - start) / (end - start)))


def health_score(r: dict) -> dict:
    """0-100 score. Each factor can only cost a capped number of points."""
    pens: list[tuple[str, float]] = [
        ("RAM usage", _ramp(r["memory"]["percent"], 60, 95, 20)),
        (f"Disk {r['disk']['drive']} usage", _ramp(r["disk"]["percent"], 70, 95, 20)),
        ("CPU load", _ramp(r["cpu"]["percent"], 50, 100, 10)),
        ("Startup programs", _ramp(len(r["startup_items"]), 8, 25, 10)),
        ("Driver errors", min(15.0, 5.0 * len(r["driver_errors"]))),
    ]
    b = r["battery"]
    if b and b["wear_percent"] is not None:
        pens.append(("Battery wear", _ramp(b["wear_percent"], 20, 60, 10)))
    lat = list(r["network"]["latency_ms"].values())
    ok = [v for v in lat if v is not None]
    net = 5.0 * (len(lat) - len(ok)) + (_ramp(sum(ok) / len(ok), 60, 250, 5) if ok else 0.0)
    if lat:
        pens.append(("Network latency", min(10.0, net)))

    value = max(0, round(100 - sum(p for _, p in pens)))
    grade, label = next((g, l) for floor, g, l in GRADES if value >= floor)
    breakdown = [{"item": n, "points_lost": round(p)}
                 for n, p in sorted(pens, key=lambda x: x[1], reverse=True) if round(p) > 0]
    return {"value": value, "grade": grade, "label": label, "breakdown": breakdown}


def quip(r: dict) -> str:
    """A friendly one-liner. Empty in --serious mode."""
    if SERIOUS:
        return ""
    boring = ("compression", "system", "registry")
    top = next((a for a in r["top_memory_apps"] if not any(b in a["name"].lower() for b in boring)), None)
    days_m = re.match(r"(\d+)d", r["uptime"])
    days = int(days_m.group(1)) if days_m else 0
    startup = len(r["startup_items"])
    value = r["score"]["value"]
    if top and top["memory_mb"] >= 1500:
        return f"{top['name']} is using {top['memory_mb'] / 1024:.1f} GB. Impressive commitment."
    if days >= 7:
        return f"Uptime: {days} days. Your PC would really enjoy a restart."
    if startup > 15:
        return f"{startup} programs launch at startup. Your boot time sends its regards."
    if value >= 90:
        return "Spotless. Your PC is in better shape than most. Go touch some grass."
    if value >= 70:
        return "Solid. A few tweaks and you're in the A club."
    return "Your PC is asking for help. The list above is a good place to start."


def sparkline(values: list[float], lo: float | None = None, hi: float | None = None) -> str:
    if not values:
        return ""
    blocks = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    lo = min(values) if lo is None else lo
    hi = max(values) if hi is None else hi
    if hi == lo:
        return blocks[0] * len(values)
    return "".join(blocks[int(min(1.0, max(0.0, (v - lo) / (hi - lo))) * (len(blocks) - 1))] for v in values)


def load_history() -> list[dict]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(entries: list[dict]) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(entries[-200:], indent=1), encoding="utf-8")
    except OSError:
        pass  # history is a nicety; never fail a scan over it


def history_entry(r: dict) -> dict:
    return {"time": r["generated_at"], "score": r["score"]["value"], "cpu": r["cpu"]["percent"],
            "ram": r["memory"]["percent"], "disk": r["disk"]["percent"],
            "startup": len(r["startup_items"])}


def compute_trend(history: list[dict], r: dict) -> list[str]:
    if not history:
        return ["First scan recorded. Run again later to see how your PC changes."]
    prev, cur = history[-1], history_entry(r)
    when = str(prev.get("time", ""))[:10]
    lines = [f"Health score {cur['score']} ({cur['score'] - prev.get('score', cur['score']):+d} "
             f"vs last scan on {when})"]
    for key, label in (("ram", "RAM"), ("disk", "Disk")):
        if isinstance(prev.get(key), (int, float)) and cur[key] != prev[key]:
            lines.append(f"{label}: {cur[key]:.1f}% ({cur[key] - prev[key]:+.1f}%)")
    if isinstance(prev.get("startup"), int) and cur["startup"] != prev["startup"]:
        lines.append(f"Startup items: {cur['startup']} ({cur['startup'] - prev['startup']:+d})")
    return lines


def show_history() -> None:
    console.rule("[bold cyan]Scan History")
    h = load_history()
    if not h:
        console.print("No history yet. Run a health scan first (it is saved automatically).")
        return
    t = Table(box=box.SIMPLE_HEAD)
    for col in ("Date", "Score", "CPU", "RAM", "Disk", "Startup"):
        t.add_column(col, justify="left" if col == "Date" else "right")
    for e in h[-15:]:
        s = e.get("score")
        color = "green" if isinstance(s, int) and s >= 80 else "yellow" if isinstance(s, int) and s >= 60 else "red"
        t.add_row(str(e.get("time", "-")), f"[{color}]{s if s is not None else '-'}[/]",
                  f"{e.get('cpu', '-')}%", f"{e.get('ram', '-')}%", f"{e.get('disk', '-')}%",
                  str(e.get("startup", "-")))
    console.print(t)
    console.print("Score trend: " + sparkline([e.get("score", 0) for e in h[-30:]], 0, 100))
    console.print(f"[dim]History file: {escape(str(HISTORY_FILE))}[/]")


def make_bar(pct: float, width: int = 30) -> str:
    n = round(width * min(100.0, max(0.0, pct)) / 100)
    full, empty = "\u2588" * n, "\u2591" * (width - n)
    return f"[{level(pct)}]{full}[/][dim]{empty}[/] {pct:5.1f}%"


def live_dashboard() -> None:
    """Auto-updating CPU / RAM / disk / network view. Ctrl+C to leave."""
    from rich.live import Live

    drive = os.environ.get("SystemDrive", "C:") + "\\"
    cpu_hist: deque = deque(maxlen=40)
    state = {"net": psutil.net_io_counters(), "t": time.time()}
    psutil.cpu_percent(None)  # prime the counter

    def render() -> Panel:
        cpu = psutil.cpu_percent(None)
        cpu_hist.append(cpu)
        vm = psutil.virtual_memory()
        now, net = time.time(), psutil.net_io_counters()
        dt = max(now - state["t"], 0.001)
        down = (net.bytes_recv - state["net"].bytes_recv) / dt
        up = (net.bytes_sent - state["net"].bytes_sent) / dt
        state["net"], state["t"] = net, now
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold")
        t.add_column()
        t.add_row("CPU", make_bar(cpu))
        t.add_row("", f"[dim]{sparkline(list(cpu_hist), 0, 100)}[/]")
        t.add_row("RAM", make_bar(vm.percent))
        try:
            t.add_row(f"Disk {drive[:2]}", make_bar(psutil.disk_usage(drive).percent))
        except OSError:
            t.add_row("Disk", "[dim]n/a[/]")
        t.add_row("Network", f"down {human_size(down)}/s   up {human_size(up)}/s")
        b = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if b:
            t.add_row("Battery", f"{b.percent:.0f}% ({'plugged in' if b.power_plugged else 'on battery'})")
        return Panel(t, title=f"SysPulse live v{VERSION}", subtitle="Ctrl+C to exit", border_style="cyan")

    with Live(render(), console=console, refresh_per_second=4) as live:
        try:
            while True:
                time.sleep(1)
                live.update(render())
        except KeyboardInterrupt:
            pass


CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>My PC Health Score: __SCORE__/100</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
         background: radial-gradient(circle at 30% 20%, #1f2a44, #0b0f19 70%);
         font-family: Segoe UI, system-ui, Arial, sans-serif; color: #e6edf3; }
  .card { width: 100%; max-width: 420px; padding: 28px; border-radius: 24px;
          background: rgba(22, 27, 38, .92); border: 1px solid #2d3548;
          box-shadow: 0 20px 60px rgba(0, 0, 0, .5); }
  .brand { font-size: 13px; letter-spacing: .12em; text-transform: uppercase; color: #8b949e; }
  .ring { position: relative; width: 160px; height: 160px; margin: 18px auto 6px; }
  .ring svg { transform: rotate(-90deg); }
  .ring .num { position: absolute; inset: 0; display: grid; place-items: center; text-align: center; }
  .num b { font-size: 44px; line-height: 1; color: __COLOR__; }
  .num span { font-size: 13px; color: #8b949e; }
  .grade { text-align: center; font-size: 18px; font-weight: 600; color: __COLOR__; }
  .quip { text-align: center; font-style: italic; color: #b6c0cc; margin: 10px 0 18px; min-height: 1.2em; }
  .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .tile { background: #0f1420; border: 1px solid #262d3f; border-radius: 14px; padding: 12px 6px; text-align: center; }
  .tv { font-size: 20px; font-weight: 700; } .tl { font-size: 11px; color: #8b949e; margin-top: 2px; }
  h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .1em; color: #8b949e; margin: 20px 0 8px; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #222a3b; font-size: 14px; }
  li b { color: #f85149; }
  .meta { margin-top: 18px; font-size: 12px; color: #8b949e; text-align: center; line-height: 1.6; }
</style></head><body>
<div class="card">
  <div class="brand">SysPulse &middot; PC Health Card</div>
  <div class="ring">
    <svg width="160" height="160" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="54" fill="none" stroke="#262d3f" stroke-width="10"/>
      <circle cx="60" cy="60" r="54" fill="none" stroke="__COLOR__" stroke-width="10" stroke-linecap="round"
              stroke-dasharray="__CIRC__" stroke-dashoffset="__OFFSET__"/>
    </svg>
    <div class="num"><div><b>__SCORE__</b><br><span>out of 100</span></div></div>
  </div>
  <div class="grade">Grade __GRADE__ &middot; __LABEL__</div>
  <div class="quip">__QUIP__</div>
  <div class="tiles">__TILES__</div>
  <h3>Costing you points</h3>
  <ul>__COSTS__</ul>
  <div class="meta">__HOG__<br>__TREND__<br>__DATE__ &middot; SysPulse v__VERSION__<br>__REPO__</div>
</div></body></html>
"""


def render_card(r: dict) -> str:
    """Screenshot-friendly summary. Deliberately omits hostname and IP addresses."""
    e = html.escape
    s = r["score"]
    v = s["value"]
    color = "#3fb950" if v >= 80 else "#d29922" if v >= 60 else "#f85149"
    circ = 2 * 3.14159265 * 54
    c, m, d, n = r["cpu"], r["memory"], r["disk"], r["network"]
    tiles = [("CPU", f"{c['percent']:.0f}%"), ("RAM", f"{m['percent']:.0f}%"),
             (f"Disk {d['drive']}", f"{d['percent']:.0f}%"), ("Startup apps", str(len(r["startup_items"])))]
    b = r["battery"]
    if b and b["wear_percent"] is not None:
        tiles.append(("Battery health", f"{100 - b['wear_percent']:.0f}%"))
    pings = [x for x in n["latency_ms"].values() if x is not None]
    if pings:
        tiles.append(("Avg ping", f"{sum(pings) / len(pings):.0f} ms"))
    tiles_html = "".join(f'<div class="tile"><div class="tv">{e(val)}</div><div class="tl">{e(lbl)}</div></div>'
                         for lbl, val in tiles)
    costs = "".join(f"<li><span>{e(x['item'])}</span><b>-{x['points_lost']}</b></li>"
                    for x in s["breakdown"][:4]) or "<li><span>Nothing. Flawless.</span></li>"
    top = next(iter(r["top_memory_apps"]), None)
    hog = f"Top memory hog: {e(top['name'])} ({top['memory_mb']} MB)" if top else ""
    trend = e(r["trend"][0]) if r.get("trend") else ""
    values = {
        "__SCORE__": str(v), "__COLOR__": color, "__CIRC__": f"{circ:.1f}",
        "__OFFSET__": f"{circ * (1 - v / 100):.1f}", "__GRADE__": e(s["grade"]), "__LABEL__": e(s["label"]),
        "__QUIP__": e(r.get("quip", "")), "__TILES__": tiles_html, "__COSTS__": costs, "__HOG__": hog,
        "__TREND__": trend, "__DATE__": e(r["generated_at"][:10]), "__VERSION__": VERSION,
        "__REPO__": e(REPO_URL),
    }
    out = CARD_TEMPLATE
    for key, val in values.items():
        out = out.replace(key, val)
    return out


# --------------------------------------------------------------------------
# Offline virus check (Windows Defender, local signatures, no internet needed)
# --------------------------------------------------------------------------
def find_mpcmdrun() -> str | None:
    """Locate Defender's command-line scanner (newest platform version first)."""
    candidates: list[Path] = []
    platform_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows Defender/Platform"
    if platform_dir.is_dir():
        def version_key(p: Path) -> tuple:
            return tuple(int(x) for x in re.findall(r"\d+", p.name))
        try:
            candidates += [d / "MpCmdRun.exe" for d in sorted(platform_dir.iterdir(), key=version_key, reverse=True)]
        except OSError:
            pass
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender/MpCmdRun.exe")
    for c in candidates:
        if c.is_file():
            return str(c)
    return None


def defender_status() -> dict | None:
    script = ("Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, "
              "AntivirusSignatureAge, AntivirusSignatureVersion | ConvertTo-Json -Compress")
    code, out = powershell(script, timeout=30)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def virus_scan(target: str = "quick", remediate: bool = False) -> int:
    """
    Scan with Windows Defender using its locally stored signatures.
    target: "quick", "full", or a file/folder path.
    By default nothing is removed (detect-only); pass remediate=True to let Defender act.
    Returns 0 = clean, 2 = threats found, 1 = scan could not run.
    """
    console.rule("[bold cyan]Offline Virus Check (Windows Defender)")
    exe = find_mpcmdrun()
    if not exe:
        console.print("[red]Windows Defender's scanner (MpCmdRun.exe) was not found.[/] "
                      "It may be removed or replaced by another antivirus.")
        return 1

    st = defender_status()
    if st:
        age = st.get("AntivirusSignatureAge")
        console.print(f"Signature version: {st.get('AntivirusSignatureVersion', 'unknown')}"
                      + (f" ({age} day(s) old)" if age is not None else ""))
        if st.get("AntivirusEnabled") is False:
            console.print("[yellow]Defender is not the active antivirus (another AV may be installed). "
                          "The scan may be limited or fail.[/]")
        if isinstance(age, int) and age > 7:
            console.print("[yellow]Signatures are over a week old. The scan still works offline "
                          "but can miss newer threats. Update them when you are online "
                          "(Windows Security > Virus & threat protection updates).[/]")

    cmd = [exe, "-Scan"]
    key = target.lower()
    if key == "quick":
        cmd += ["-ScanType", "1"]
        label = "quick scan"
    elif key == "full":
        cmd += ["-ScanType", "2"]
        label = "full scan (this can take a long time)"
    else:
        if not os.path.exists(target):
            console.print(f"[red]Path not found:[/] {escape(target)}")
            return 1
        cmd += ["-ScanType", "3", "-File", target]
        label = f"custom scan of {target}"
    if not remediate:
        cmd.append("-DisableRemediation")

    console.print(f"Running {escape(label)} ({'remove/quarantine enabled' if remediate else 'detect-only'})...")
    try:
        with console.status("Scanning with local signatures. Press Ctrl+C to cancel..."):
            r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    except OSError as exc:
        console.print(f"[red]Could not start the scanner: {escape(str(exc))}[/]")
        return 1

    output = (r.stdout or "").strip()
    if r.returncode == 0:
        console.print("[green]Scan finished: no threats found.[/]")
        return 0
    if r.returncode == 2:
        console.print("[bold red]Threats were detected![/]")
        for line in output.splitlines():
            if "threat" in line.lower():
                console.print(f"  {escape(line.strip())}")
        console.print("Review them in Windows Security > Virus & threat protection > Protection history.")
        return 2
    console.print(f"[yellow]The scan did not complete (exit code {r.returncode}).[/] "
                  "Try again from an Administrator terminal.")
    for line in output.splitlines()[-10:]:
        console.print(f"  {escape(line)}")
    return 1


def menu_virus_scan() -> None:
    mode = Prompt.ask("Scan type: quick, full (can take hours) or custom folder/file",
                      choices=["quick", "full", "custom"], default="quick")
    target = mode
    if mode == "custom":
        target = os.path.abspath(Prompt.ask("File or folder path").strip().strip('"'))
    remediate = Confirm.ask("Let Defender remove/quarantine anything it finds? (No = report only)",
                            default=False)
    virus_scan(target, remediate)


# --------------------------------------------------------------------------
# Interactive menu
# --------------------------------------------------------------------------
MENU = """[bold]1[/]  Full PC health scan + export
[bold]2[/]  Flush DNS cache
[bold]3[/]  Clean loose temp files
[bold]4[/]  Startup program inspector
[bold]5[/]  Network check (IPs + ping)
[bold]6[/]  Battery health
[bold]7[/]  Large file finder
[bold]8[/]  Windows Update & system file check
[bold]9[/]  Offline virus check (Windows Defender)
[bold]10[/] Live dashboard
[bold]11[/] Scan history & trends
[bold]0[/]  Exit"""


def menu_large_files() -> None:
    choice = Prompt.ask("Scan which location? 1=Downloads  2=C:\\Users  3=Custom path",
                        choices=["1", "2", "3"], default="1")
    if choice == "1":
        show_large_files(str(Path.home() / "Downloads"))
    elif choice == "2":
        show_large_files(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "Users"))
    else:
        show_large_files(Prompt.ask("Folder path").strip().strip('"'))


def interactive_menu() -> None:
    while True:
        console.print(Panel(MENU, title=f"SysPulse v{VERSION}", border_style="cyan", expand=False))
        choice = Prompt.ask("Select an option", choices=[str(i) for i in range(12)], default="0")
        if choice == "0":
            return
        if choice == "1":
            fmt = Prompt.ask("Export format", choices=["txt", "json", "html", "card", "all"], default="txt")
            run_scan(fmt)
        elif choice == "2":
            flush_dns()
        elif choice == "3":
            clean_temp(confirm=True)
        elif choice == "4":
            show_startup()
        elif choice == "5":
            show_network()
        elif choice == "6":
            show_battery()
        elif choice == "7":
            menu_large_files()
        elif choice == "8":
            show_pending_updates()
            run_integrity_checks(run_sfc=is_admin() and Confirm.ask(
                "Also run sfc /verifyonly? (slow)", default=False))
        elif choice == "9":
            menu_virus_scan()
        elif choice == "10":
            live_dashboard()
        elif choice == "11":
            show_history()
        Prompt.ask("\nPress Enter to return to the menu", default="", show_default=False)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="syspulse",
        description="SysPulse - Windows PC health & utility CLI. Run with no flags for the interactive menu.")
    p.add_argument("--scan", action="store_true", help="run the full health scan and export a report")
    p.add_argument("--format", choices=["txt", "json", "html", "card", "all"], default="txt",
                   help="report format for --scan (default: txt)")
    p.add_argument("--clean", action="store_true", help="delete loose files in %%TEMP%% (no prompt)")
    p.add_argument("--flush-dns", action="store_true", help="flush the Windows DNS cache")
    p.add_argument("--startup", action="store_true", help="list startup programs")
    p.add_argument("--network", action="store_true", help="show local/public IP and DNS ping latency")
    p.add_argument("--battery", action="store_true", help="show battery wear and save a powercfg report")
    p.add_argument("--large-files", nargs="?", const="", metavar="PATH",
                   help="list the 10 largest files (default: Downloads)")
    p.add_argument("--updates", action="store_true", help="list pending Windows updates")
    p.add_argument("--integrity", action="store_true",
                   help="run DISM /CheckHealth and sfc /verifyonly (needs Administrator)")
    p.add_argument("--virus-scan", nargs="?", const="quick", metavar="quick|full|PATH",
                   help="offline virus check with Windows Defender (default: quick); "
                        "exit code 2 means threats were found")
    p.add_argument("--remediate", action="store_true",
                   help="let Defender remove/quarantine threats found by --virus-scan (default: detect-only)")
    p.add_argument("--live", action="store_true", help="live auto-updating CPU/RAM/disk/network dashboard")
    p.add_argument("--history", action="store_true", help="show past scan scores and trends")
    p.add_argument("--no-net", action="store_true",
                   help="privacy mode for --scan: no public-IP lookup and no pings")
    p.add_argument("--serious", action="store_true", help="turn off the playful one-liners")
    p.add_argument("--no-color", action="store_true", help="disable colored output (useful for logs)")
    p.add_argument("--version", action="version", version=f"SysPulse {VERSION}")
    return p


def main(argv: list[str] | None = None) -> int:
    global console, SERIOUS
    args = build_parser().parse_args(argv)
    SERIOUS = args.serious
    if args.no_color:
        console = Console(no_color=True, highlight=False)

    jobs = [
        (args.scan, lambda: run_scan(args.format, args.no_net)),
        (args.live, live_dashboard),
        (args.history, show_history),
        (args.clean, lambda: clean_temp(confirm=False)),
        (args.flush_dns, flush_dns),
        (args.startup, show_startup),
        (args.network, show_network),
        (args.battery, show_battery),
        (args.large_files is not None, lambda: show_large_files(args.large_files or None)),
        (args.updates, show_pending_updates),
        (args.integrity, lambda: run_integrity_checks(run_sfc=True)),
        (args.virus_scan is not None, lambda: virus_scan(args.virus_scan, args.remediate)),
    ]
    exit_code = 0
    try:
        if any(flag for flag, _ in jobs):
            for flag, job in jobs:
                if flag:
                    result = job()
                    if isinstance(result, int):
                        exit_code = max(exit_code, result)
        else:
            interactive_menu()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
        return 130
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
