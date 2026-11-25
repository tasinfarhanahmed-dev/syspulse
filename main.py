import os
import platform
import socket
import subprocess
import datetime
import shutil
import tempfile
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
    # Find Windows devices with driver issues
    cmd = ["powershell", "-Command", "Get-PnpDevice | Where-Object {$_.Status -ne 'OK' -and $_.Status -ne 'Unknown'} | Select-Object -ExpandProperty FriendlyName"]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, universal_newlines=True).strip()
        return out.splitlines() if out else []
    except Exception:
        return ["Scan failed"]

def get_top_ram_apps():
    # Combine RAM usage by app name and return top 3
    totals = {}
    for proc in psutil.process_iter(['name', 'memory_info']):
        try:
            name = proc.info['name']
            mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
            totals[name] = totals.get(name, 0) + mem_mb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)[:3]

def get_uptime_and_battery():
    # Calculate system uptime and check battery if laptop
    boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
    uptime = str(datetime.datetime.now() - boot_time).split('.')[0]
    
    battery = psutil.sensors_battery()
    if battery:
        status = "Charging" if battery.power_plugged else "On Battery"
        bat_info = f"{battery.percent}% ({status})"
    else:
        bat_info = "Desktop PC (No Battery)"
    return uptime, bat_info

def run_diagnostics():
    print("\n🔍 Scanning system health and network...\n")

    ram = psutil.virtual_memory()
    disk = shutil.disk_usage("C:\\")
    cpu = psutil.cpu_percent(interval=1)
    uptime, battery = get_uptime_and_battery()

    google_ping = check_ping("8.8.8.8")
    cloudflare_ping = check_ping("1.1.1.1")
    broken_drivers = check_problem_devices()
    top_apps = get_top_ram_apps()

    report = [
        "==========================================",
        "    SYSPULSE v2.0 - DIAGNOSTIC REPORT     ",
        "==========================================",
        f"Date/Time      : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"PC Name        : {socket.gethostname()}",
        f"OS Version     : {platform.system()} {platform.release()} (Build {platform.version()})",
        f"System Uptime  : {uptime}",
        f"Power/Battery  : {battery}",
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

    report.append("------------------------------------------")
    report.append("SMART RECOMMENDATIONS:")
    if ram.percent > 85:
        report.append("  [!] High RAM usage! Close heavy apps.")
    if disk.free / disk.total < 0.15:
        report.append("  [!] Low C: drive space! Run Temp Cleaner.")
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

def flush_dns():
    # Clear Windows DNS resolver cache
    print("\n🌐 Flushing Windows DNS cache...")
    try:
        subprocess.run(
            ["powershell", "-Command", "Clear-DnsClientCache"],
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Windows DNS cache successfully flushed!")
    except subprocess.CalledProcessError:
        print("⚠️ Access denied! Right-click SysPulse (or VS Code) and choose 'Run as administrator' to flush DNS.")

def clean_temp_files():
    # Delete only loose files directly inside the main Windows Temp folder
    temp_dir = tempfile.gettempdir()
    print(f"\n🧹 Scanning loose files in: {temp_dir}")
    freed_bytes = 0
    deleted_count = 0

    for item in os.listdir(temp_dir):
        item_path = os.path.join(temp_dir, item)
        if os.path.isfile(item_path) or os.path.islink(item_path):
            try:
                size = os.path.getsize(item_path)
                os.unlink(item_path)
                freed_bytes += size
                deleted_count += 1
            except Exception:
                # Skip files actively locked by open apps
                pass

    if deleted_count == 0:
        print("✨ Temp folder is already clean — nothing to delete!")
    else:
        freed_mb = round(freed_bytes / (1024 * 1024), 2)
        print(f"✅ Cleaned {deleted_count} files and freed {freed_mb} MB!")

def main_menu():
    while True:
        print("\n==========================================")
        print("         SYSPULSE v2.0 - MAIN MENU        ")
        print("==========================================")
        print("  [1] Run Full PC Health & Network Report")
        print("  [2] Flush Windows DNS Cache (Fix Lag)")
        print("  [3] Clean Windows Temp Junk Files")
        print("  [4] Exit")
        print("==========================================")
        
        choice = input("Choose an option (1-4): ").strip()

        if choice == "1":
            run_diagnostics()
        elif choice == "2":
            flush_dns()
        elif choice == "3":
            clean_temp_files()
        elif choice == "4":
            print("👋 Goodbye!")
            break
        else:
            print("⚠️ Invalid choice. Please enter 1, 2, 3, or 4.")

if __name__ == "__main__":
    main_menu()
