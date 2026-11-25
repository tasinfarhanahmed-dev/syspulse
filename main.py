import os
import platform
import socket
import subprocess
import datetime
import shutil
import psutil

def check_ping(host):
    # Ping host twice and return average latency
    cmd = ["ping", "-n", "2", host]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True)
        for line in out.splitlines():
            if "Average" in line:
                return line.split("Average =")[-1].strip()
        return "Reachable"
    except subprocess.CalledProcessError:
        return "Timed Out"

def check_problem_devices():
    # Find driver issues
    cmd = ["powershell", "-Command", "Get-PnpDevice | Where-Object {$_.Status -ne 'OK' -and $_.Status -ne 'Unknown'} | Select-Object -ExpandProperty FriendlyName"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True).strip()
        return out.splitlines() if out else []
    except Exception:
        return ["Scan failed"]

def get_top_ram_apps():
    # Get top 3 memory-consuming processes
    apps = []
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
            apps.append((proc.info['name'], mem_mb))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    apps.sort(key=lambda x: x[1], reverse=True)
    return apps[:3]

def run_diagnostics():
    print("🔍 Scanning system...\n")

    # Collect hardware stats
    ram = psutil.virtual_memory()
    disk = shutil.disk_usage("C:\\")
    cpu = psutil.cpu_percent(interval=1)

    # Collect network and driver stats
    google_ping = check_ping("8.8.8.8")
    cloudflare_ping = check_ping("1.1.1.1")
    broken_drivers = check_problem_devices()
    top_apps = get_top_ram_apps()

    # Build report text
    report = [
        "==========================================",
        "       PC HEALTH & DIAGNOSTIC REPORT      ",
        "==========================================",
        f"Date/Time      : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"PC Name        : {socket.gethostname()}",
        f"OS Version     : {platform.system()} {platform.release()} (Build {platform.version()})",
        f"CPU Usage      : {cpu}%",
        f"RAM Usage      : {ram.percent}% ({round(ram.used / (1024**3), 1)} GB / {round(ram.total / (1024**3), 1)} GB)",
        f"C: Drive Free  : {round(disk.free / (1024**3), 1)} GB free of {round(disk.total / (1024**3), 1)} GB",
        "------------------------------------------",
        "TOP MEMORY APPS:"
    ]

    for name, mem in top_apps:
        clean_name = name.replace("MemCompression", "Mem Compression").replace(".exe", "")
        report.append(f"  • {clean_name}: {round(mem)} MB")

    report.extend([
        "------------------------------------------",
        "NETWORK LATENCY:",
        f"  Google DNS (8.8.8.8)     : {google_ping}",
        f"  Cloudflare DNS (1.1.1.1) : {cloudflare_ping}",
        "------------------------------------------",
        "DRIVER & HARDWARE STATUS:"
    ])

    if broken_drivers:
        for dev in broken_drivers:
            report.append(f"  [!] Issue found: {dev}")
    else:
        report.append("  [✓] All active drivers working normally.")

    # Add health tips
    report.append("------------------------------------------")
    report.append("SMART RECOMMENDATIONS:")
    if ram.percent > 85:
        report.append("  [!] High RAM usage! Close heavy apps.")
    if disk.free / disk.total < 0.15:
        report.append("  [!] Low C: drive space! Run Disk Cleanup.")
    if ram.percent <= 85 and (disk.free / disk.total >= 0.15):
        report.append("  [✓] System resources look healthy!")

    report.append("==========================================")

    final_output = "\n".join(report)
    print(final_output)

    # Save report to Desktop and open it
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    save_dir = desktop if os.path.exists(desktop) else os.getcwd()
    file_path = os.path.join(save_dir, f"health_report_{timestamp}.txt")

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(final_output)

    print(f"\n✅ Saved to: {file_path}")
    os.startfile(file_path)
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    run_diagnostics()
