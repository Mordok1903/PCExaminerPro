"""
PC Examiner Pro - Aplicativo de diagnóstico de PC
Desarrollado con Python + CustomTkinter
"""

import sys
import os
import threading
import subprocess
import ctypes
import platform

# Verificar si se ejecuta como administrador
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    # Re-ejecutar como administrador
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit()

import customtkinter as ctk
from tkinter import messagebox, filedialog
import psutil
import time
import datetime
import json
import tempfile
import glob
import winreg
import socket
import re

# Intentar importar módulos opcionales
try:
    import wmi
    WMI_AVAILABLE = True
except:
    WMI_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except:
    REPORTLAB_AVAILABLE = False

# ─────────────────────────────────────────────
# CONFIGURACIÓN DE TEMA
# ─────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Colores del tema
COLORS = {
    "bg_dark": "#0d1117",
    "bg_card": "#161b22",
    "bg_card2": "#1c2128",
    "accent_blue": "#58a6ff",
    "accent_green": "#3fb950",
    "accent_orange": "#f78166",
    "accent_yellow": "#e3b341",
    "accent_purple": "#bc8cff",
    "accent_red": "#ff4444",
    "text_primary": "#e6edf3",
    "text_secondary": "#8b949e",
    "border": "#30363d",
    "success": "#238636",
    "warning": "#9e6a03",
    "danger": "#da3633",
    "good": "#196c2e",
}

STATUS_COLORS = {
    "BUENO": "#3fb950",
    "ADVERTENCIA": "#e3b341",
    "CRÍTICO": "#ff4444",
    "INFO": "#58a6ff",
    "DESCONOCIDO": "#8b949e",
}


# ─────────────────────────────────────────────
# MÓDULOS DE DIAGNÓSTICO
# ─────────────────────────────────────────────

class DiagnosticEngine:
    def __init__(self):
        self.results = {}
        self.report_data = []

    def get_system_info(self):
        """Información básica del sistema"""
        info = {}
        try:
            info["os"] = f"{platform.system()} {platform.release()} {platform.version()}"
            info["machine"] = platform.machine()
            info["processor"] = platform.processor()
            info["hostname"] = socket.gethostname()
            info["python"] = platform.python_version()
            boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
            info["boot_time"] = boot_time.strftime("%Y-%m-%d %H:%M:%S")
            uptime = datetime.datetime.now() - boot_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)
            info["uptime"] = f"{hours}h {minutes}m"
        except Exception as e:
            info["error"] = str(e)
        return info

    def check_disk_health(self):
        """Estado de los discos"""
        disks = []
        try:
            partitions = psutil.disk_partitions()
            for partition in partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    percent_used = usage.percent
                    status = "BUENO"
                    if percent_used > 90:
                        status = "CRÍTICO"
                    elif percent_used > 75:
                        status = "ADVERTENCIA"

                    disk_info = {
                        "device": partition.device,
                        "mountpoint": partition.mountpoint,
                        "fstype": partition.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "percent": percent_used,
                        "status": status,
                    }
                    disks.append(disk_info)
                except:
                    pass

            # SMART via wmi
            if WMI_AVAILABLE:
                try:
                    c = wmi.WMI()
                    for disk in c.Win32_DiskDrive():
                        for d in disks:
                            if disk.DeviceID in d["device"] or d["device"] in disk.DeviceID:
                                d["model"] = disk.Model or "Desconocido"
                                d["size_bytes"] = disk.Size
                                d["interface"] = disk.InterfaceType or "Desconocido"
                                d["media_type"] = disk.MediaType or "Desconocido"
                except:
                    pass
        except Exception as e:
            disks = [{"error": str(e)}]
        return disks

    def check_temp_files(self):
        """Archivos temporales y basura"""
        temp_locations = []
        total_size = 0

        paths_to_check = [
            (os.environ.get("TEMP", ""), "Carpeta TEMP del usuario"),
            (os.environ.get("TMP", ""), "Carpeta TMP del usuario"),
            (r"C:\Windows\Temp", "Carpeta TEMP de Windows"),
            (r"C:\Windows\Prefetch", "Prefetch de Windows"),
        ]

        # Agregar caché de navegadores si existe
        appdata = os.environ.get("LOCALAPPDATA", "")
        browser_caches = [
            (os.path.join(appdata, r"Google\Chrome\User Data\Default\Cache"), "Caché Chrome"),
            (os.path.join(appdata, r"Microsoft\Edge\User Data\Default\Cache"), "Caché Edge"),
            (os.path.join(appdata, r"Mozilla\Firefox\Profiles"), "Caché Firefox"),
        ]
        paths_to_check.extend(browser_caches)

        for path, name in paths_to_check:
            if path and os.path.exists(path):
                try:
                    size = self._get_folder_size(path)
                    total_size += size
                    temp_locations.append({
                        "name": name,
                        "path": path,
                        "size_mb": round(size / (1024**2), 2),
                        "size_gb": round(size / (1024**3), 3),
                    })
                except:
                    pass

        return {
            "locations": temp_locations,
            "total_mb": round(total_size / (1024**2), 2),
            "total_gb": round(total_size / (1024**3), 3),
            "status": "ADVERTENCIA" if total_size > 1 * 1024**3 else "BUENO",
        }

    def _get_folder_size(self, path, time_limit=5.0):
        """Calcula el tamaño de una carpeta con límite de tiempo para evitar bloqueos."""
        total = 0
        deadline = time.time() + time_limit
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                if time.time() > deadline:
                    break  # Se agotó el tiempo, devuelve lo calculado hasta ahora
                for f in filenames:
                    try:
                        fp = os.path.join(dirpath, f)
                        if os.path.exists(fp):
                            total += os.path.getsize(fp)
                    except:
                        pass
        except:
            pass
        return total

    def clean_temp_files(self, progress_callback=None):
        """Limpiar archivos temporales"""
        cleaned = 0
        errors = 0
        
        # Obtenemos las mismas rutas que en check_temp_files
        paths_to_clean = [
            os.environ.get("TEMP", ""),
            os.environ.get("TMP", ""),
            r"C:\Windows\Temp",
            r"C:\Windows\Prefetch",
        ]
        
        appdata = os.environ.get("LOCALAPPDATA", "")
        paths_to_clean.extend([
            os.path.join(appdata, r"Google\Chrome\User Data\Default\Cache"),
            os.path.join(appdata, r"Microsoft\Edge\User Data\Default\Cache"),
            os.path.join(appdata, r"Mozilla\Firefox\Profiles")
        ])

        for path in paths_to_clean:
            if path and os.path.exists(path):
                for item in os.listdir(path):
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path):
                            size = os.path.getsize(item_path)
                            os.remove(item_path)
                            cleaned += size
                        elif os.path.isdir(item_path):
                            import shutil
                            size = self._get_folder_size(item_path)
                            shutil.rmtree(item_path, ignore_errors=True)
                            cleaned += size
                    except:
                        errors += 1
                    if progress_callback:
                        progress_callback()

        return {
            "cleaned_mb": round(cleaned / (1024**2), 2),
            "errors": errors,
        }

    def check_cpu_ram(self):
        """Estado de CPU y RAM"""
        cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        cpu_avg = sum(cpu_percent) / len(cpu_percent)
        ram_status = "BUENO"
        if memory.percent > 90:
            ram_status = "CRÍTICO"
        elif memory.percent > 75:
            ram_status = "ADVERTENCIA"

        cpu_status = "BUENO"
        if cpu_avg > 90:
            cpu_status = "CRÍTICO"
        elif cpu_avg > 75:
            cpu_status = "ADVERTENCIA"

        return {
            "cpu_cores": psutil.cpu_count(logical=False),
            "cpu_threads": psutil.cpu_count(logical=True),
            "cpu_percent_per_core": cpu_percent,
            "cpu_percent_avg": round(cpu_avg, 1),
            "cpu_freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
            "cpu_freq_max_mhz": round(cpu_freq.max, 0) if cpu_freq else None,
            "ram_total_gb": round(memory.total / (1024**3), 2),
            "ram_used_gb": round(memory.used / (1024**3), 2),
            "ram_available_gb": round(memory.available / (1024**3), 2),
            "ram_percent": memory.percent,
            "swap_total_gb": round(swap.total / (1024**3), 2),
            "swap_used_gb": round(swap.used / (1024**3), 2),
            "swap_percent": swap.percent,
            "cpu_status": cpu_status,
            "ram_status": ram_status,
        }

    def check_temperatures(self):
        """Temperaturas del sistema"""
        temps = {}
        try:
            sensors = psutil.sensors_temperatures()
            if sensors:
                for name, entries in sensors.items():
                    temps[name] = []
                    for entry in entries:
                        status = "BUENO"
                        if entry.current >= 90:
                            status = "CRÍTICO"
                        elif entry.current >= 75:
                            status = "ADVERTENCIA"
                        temps[name].append({
                            "label": entry.label or name,
                            "current": entry.current,
                            "high": entry.high,
                            "critical": entry.critical,
                            "status": status,
                        })
        except:
            pass

        # Intentar obtener temp via WMI si no hay datos
        if not temps and WMI_AVAILABLE:
            try:
                c = wmi.WMI(namespace=r"root\OpenHardwareMonitor")
                sensors = c.Sensor()
                for sensor in sensors:
                    if sensor.SensorType == "Temperature":
                        if sensor.Name not in temps:
                            temps[sensor.Name] = []
                        status = "BUENO"
                        if sensor.Value >= 90:
                            status = "CRÍTICO"
                        elif sensor.Value >= 75:
                            status = "ADVERTENCIA"
                        temps[sensor.Name].append({
                            "label": sensor.Name,
                            "current": sensor.Value,
                            "status": status,
                        })
            except:
                pass

        return temps if temps else {"info": "Temperaturas no disponibles en este sistema"}

    def check_battery(self):
        """Estado de la batería"""
        battery = psutil.sensors_battery()
        if battery is None:
            return {"available": False, "message": "No se detectó batería (PC de escritorio o sin soporte)"}

        status = "BUENO"
        if battery.percent < 20 and not battery.power_plugged:
            status = "CRÍTICO"
        elif battery.percent < 40 and not battery.power_plugged:
            status = "ADVERTENCIA"

        result = {
            "available": True,
            "percent": battery.percent,
            "plugged": battery.power_plugged,
            "status": status,
        }

        if battery.secsleft != psutil.POWER_TIME_UNLIMITED and battery.secsleft != psutil.POWER_TIME_UNKNOWN:
            hours = battery.secsleft // 3600
            minutes = (battery.secsleft % 3600) // 60
            result["time_left"] = f"{hours}h {minutes}m"
        else:
            result["time_left"] = "Cargando / Ilimitado" if battery.power_plugged else "Calculando..."

        # Estado de salud de la batería via WMI
        if WMI_AVAILABLE:
            try:
                c = wmi.WMI()
                for battery_wmi in c.Win32_Battery():
                    result["design_capacity"] = getattr(battery_wmi, "DesignCapacity", "N/A")
                    result["full_charge_capacity"] = getattr(battery_wmi, "FullChargeCapacity", "N/A")
                    result["chemistry"] = getattr(battery_wmi, "Chemistry", "N/A")
                    result["name"] = getattr(battery_wmi, "Name", "Batería")
                    dc = getattr(battery_wmi, "DesignCapacity", None)
                    fc = getattr(battery_wmi, "FullChargeCapacity", None)
                    if dc and fc and dc > 0:
                        health_pct = (fc / dc) * 100
                        result["health_percent"] = round(health_pct, 1)
                        if health_pct < 50:
                            status = "CRÍTICO"
                        elif health_pct < 75:
                            status = "ADVERTENCIA"
                        result["status"] = status
            except:
                pass

        return result

    def check_startup_programs(self):
        """Programas que inician con Windows"""
        startup_items = []
        reg_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
        ]

        for hive, path in reg_paths:
            try:
                key = winreg.OpenKey(hive, path)
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        startup_items.append({
                            "name": name,
                            "command": value,
                            "location": f"{'HKCU' if hive == winreg.HKEY_CURRENT_USER else 'HKLM'}\\{path}",
                        })
                        i += 1
                    except WindowsError:
                        break
                winreg.CloseKey(key)
            except:
                pass

        # También en carpetas de inicio
        startup_folders = [
            os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup",
        ]
        for folder in startup_folders:
            if os.path.exists(folder):
                for item in os.listdir(folder):
                    startup_items.append({
                        "name": item,
                        "command": os.path.join(folder, item),
                        "location": "Carpeta Startup",
                    })

        status = "BUENO"
        if len(startup_items) > 15:
            status = "ADVERTENCIA"
        elif len(startup_items) > 25:
            status = "CRÍTICO"

        return {
            "items": startup_items,
            "count": len(startup_items),
            "status": status,
        }

    def check_windows_updates(self):
        """Verificar actualizaciones de Windows usando método rápido (UsoClient / registro).
        Evita el COM object Microsoft.Update.Session que puede tardar minutos."""
        updates = {"available": [], "status": "INFO", "message": ""}
        try:
            # Método rápido: consultar el registro de Windows Update
            # Mucho más veloz que instanciar el COM object
            ps_cmd = (
                "$wu = New-Object -ComObject Microsoft.Update.AutoUpdate; "
                "$res = $wu.Results; "
                "if ($res -ne $null) { "
                "  $last = $res.LastSearchSuccessDate; "
                "  Write-Output \"LastSearch:$last\" "
                "} "
                "$pending = (Get-ItemProperty -Path "
                "'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired' "
                "-ErrorAction SilentlyContinue); "
                "if ($pending -ne $null) { Write-Output 'RebootRequired:True' } "
                "else { Write-Output 'RebootRequired:False' }"
            )
            result = subprocess.run(
                ["powershell", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout.strip()
            reboot_required = "RebootRequired:True" in output
            if reboot_required:
                updates["count"] = 1
                updates["status"] = "ADVERTENCIA"
                updates["message"] = "Hay actualizaciones instaladas que requieren reinicio"
            else:
                updates["count"] = 0
                updates["status"] = "BUENO"
                updates["message"] = "No hay reinicio pendiente por actualizaciones"
        except subprocess.TimeoutExpired:
            updates["status"] = "INFO"
            updates["message"] = "Verificacion de actualizaciones omitida (timeout)"
            updates["count"] = -1
        except Exception as e:
            updates["status"] = "INFO"
            updates["message"] = f"No se pudo verificar: {str(e)[:100]}"
            updates["count"] = -1
        return updates

    def check_network(self):
        """Estado de la red"""
        net_info = {}
        try:
            net_info["hostname"] = socket.gethostname()
            net_info["ip_local"] = socket.gethostbyname(socket.gethostname())
        except:
            net_info["ip_local"] = "Desconocida"

        # Interfaces de red
        interfaces = []
        try:
            net_if = psutil.net_if_stats()
            net_addrs = psutil.net_if_addrs()
            for iface, stats in net_if.items():
                iface_info = {
                    "name": iface,
                    "is_up": stats.isup,
                    "speed_mbps": stats.speed,
                    "addresses": [],
                }
                if iface in net_addrs:
                    for addr in net_addrs[iface]:
                        if addr.family == socket.AF_INET:
                            iface_info["addresses"].append(addr.address)
                interfaces.append(iface_info)
        except:
            pass

        net_info["interfaces"] = interfaces

        # Ping a servidores conocidos
        ping_targets = [("Google DNS", "8.8.8.8"), ("Cloudflare", "1.1.1.1")]
        ping_results = []
        for name, ip in ping_targets:
            try:
                result = subprocess.run(
                    ["ping", "-n", "2", ip],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    match = re.search(r"Media = (\d+)ms|Average = (\d+)ms", result.stdout)
                    avg_ms = match.group(1) or match.group(2) if match else "N/A"
                    status = "BUENO"
                    if avg_ms != "N/A" and int(avg_ms) > 100:
                        status = "ADVERTENCIA"
                    ping_results.append({"target": name, "ip": ip, "avg_ms": avg_ms, "status": status})
                else:
                    ping_results.append({"target": name, "ip": ip, "avg_ms": "Sin respuesta", "status": "CRÍTICO"})
            except:
                ping_results.append({"target": name, "ip": ip, "avg_ms": "Error", "status": "CRÍTICO"})

        net_info["ping_results"] = ping_results

        try:
            net_io = psutil.net_io_counters()
            net_info["bytes_sent_mb"] = round(net_io.bytes_sent / (1024**2), 2)
            net_info["bytes_recv_mb"] = round(net_io.bytes_recv / (1024**2), 2)
            net_info["packets_sent"] = net_io.packets_sent
            net_info["packets_recv"] = net_io.packets_recv
            net_info["errors_in"] = net_io.errin
            net_info["errors_out"] = net_io.errout
        except:
            pass

        all_up = any(iface.get("is_up") for iface in interfaces if iface.get("name") not in ["Loopback Pseudo-Interface 1"])
        net_info["status"] = "BUENO" if all_up else "ADVERTENCIA"
        return net_info

    def check_drivers(self):
        """Drivers desactualizados (vía WMI) con timeout para no bloquear el escaneo."""
        drivers_info = {"drivers": [], "status": "INFO", "message": ""}
        if not WMI_AVAILABLE:
            drivers_info["message"] = "WMI no disponible"
            return drivers_info

        result_holder = [None]
        def _wmi_query():
            try:
                c = wmi.WMI()
                ok_devices = []
                # Win32_PnPSignedDriver puede ser muy lento; limitamos a dispositivos con nombre
                for device in c.Win32_PnPSignedDriver():
                    if not device.DeviceName:
                        continue
                    ok_devices.append({
                        "name": device.DeviceName or "Desconocido",
                        "manufacturer": device.Manufacturer or "Desconocido",
                        "driver_version": device.DriverVersion or "N/A",
                        "driver_date": device.DriverDate or "N/A",
                        "status": "BUENO",
                    })

                problem_devices = []
                for device in c.Win32_PnPEntity(ConfigManagerErrorCode__notin=[0]):
                    if device.Name:
                        problem_devices.append({
                            "name": device.Name,
                            "error_code": device.ConfigManagerErrorCode,
                            "status": "CRÍTICO",
                            "manufacturer": device.Manufacturer or "Desconocido",
                        })

                result_holder[0] = {
                    "problem_drivers": problem_devices,
                    "ok_count": len(ok_devices),
                    "problem_count": len(problem_devices),
                    "status": "CRÍTICO" if problem_devices else "BUENO",
                    "message": (
                        f"{len(problem_devices)} dispositivo(s) con problemas"
                        if problem_devices
                        else "Todos los dispositivos funcionan correctamente"
                    ),
                }
            except Exception as e:
                result_holder[0] = {"error": str(e)}

        t = threading.Thread(target=_wmi_query, daemon=True)
        t.start()
        t.join(timeout=20)  # Máximo 20 segundos para la consulta WMI

        if result_holder[0] and "error" not in result_holder[0]:
            drivers_info.update(result_holder[0])
        elif result_holder[0] and "error" in result_holder[0]:
            drivers_info["message"] = f"Error al verificar: {result_holder[0]['error'][:100]}"
        else:
            # Timeout: la consulta WMI tardó más de 20s
            drivers_info["status"] = "INFO"
            drivers_info["message"] = "Consulta de drivers omitida (timeout de 20s). Abre el Administrador de Dispositivos manualmente."
        return drivers_info

    def check_security(self):
        """Escaneo basico de seguridad (estado de defensas del sistema)"""
        security = {"checks": [], "status": "BUENO"}

        # Windows Defender status via PowerShell
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-MpComputerStatus | Select-Object -Property AMServiceEnabled, RealTimeProtectionEnabled, AntivirusSignatureLastUpdated, QuickScanAge, AntispywareEnabled | ConvertTo-Json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout:
                try:
                    defender = json.loads(result.stdout)
                    am_enabled = defender.get("AMServiceEnabled", False)
                    rt_enabled = defender.get("RealTimeProtectionEnabled", False)
                    spy_enabled = defender.get("AntispywareEnabled", False)
                    security["checks"].append({
                        "name": "Windows Defender (Servicio)",
                        "value": "Activo" if am_enabled else "Inactivo",
                        "status": "BUENO" if am_enabled else "CRITICO",
                    })
                    security["checks"].append({
                        "name": "Proteccion en Tiempo Real",
                        "value": "Activa" if rt_enabled else "Inactiva",
                        "status": "BUENO" if rt_enabled else "CRITICO",
                    })
                    security["checks"].append({
                        "name": "Proteccion Anti-Spyware",
                        "value": "Activa" if spy_enabled else "Inactiva",
                        "status": "BUENO" if spy_enabled else "ADVERTENCIA",
                    })
                    scan_age = defender.get("QuickScanAge", None)
                    if scan_age is not None:
                        scan_status = "BUENO" if scan_age <= 7 else "ADVERTENCIA"
                        security["checks"].append({
                            "name": "Ultimo escaneo rapido",
                            "value": f"Hace {scan_age} dias",
                            "status": scan_status,
                        })
                    if not am_enabled or not rt_enabled:
                        security["status"] = "CRITICO"
                except:
                    pass
        except:
            pass

        # Firewall status
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetFirewallProfile | Select-Object Name, Enabled | ConvertTo-Json"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout:
                try:
                    profiles = json.loads(result.stdout)
                    if isinstance(profiles, dict):
                        profiles = [profiles]
                    for profile in profiles:
                        enabled = profile.get("Enabled", False)
                        security["checks"].append({
                            "name": f"Firewall ({profile.get('Name', 'Perfil')})",
                            "value": "Activo" if enabled else "Inactivo",
                            "status": "BUENO" if enabled else "ADVERTENCIA",
                        })
                        if not enabled and security["status"] == "BUENO":
                            security["status"] = "ADVERTENCIA"
                except:
                    pass
        except:
            pass

        # UAC status
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
            )
            uac_value, _ = winreg.QueryValueEx(key, "EnableLUA")
            winreg.CloseKey(key)
            security["checks"].append({
                "name": "Control de Cuentas de Usuario (UAC)",
                "value": "Activo" if uac_value else "Inactivo",
                "status": "BUENO" if uac_value else "ADVERTENCIA",
            })
        except:
            pass

        # Actualizaciones automaticas
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update"
            )
            au_options, _ = winreg.QueryValueEx(key, "AUOptions")
            winreg.CloseKey(key)
            auto_update = au_options in [3, 4]
            security["checks"].append({
                "name": "Actualizaciones Automaticas",
                "value": "Activas" if auto_update else "Desactivadas",
                "status": "BUENO" if auto_update else "ADVERTENCIA",
            })
        except:
            security["checks"].append({
                "name": "Actualizaciones Automaticas",
                "value": "No se pudo verificar",
                "status": "INFO",
            })

        return security

    # ────────────────────────────────────
    # ANÁLISIS DE AMENAZAS (NUEVO)
    # ────────────────────────────────────

    # Lista de procesos malware conocidos (nombres de ejecutables)
    KNOWN_MALWARE_PROCESSES = {
        # RATs / Troyanos
        "njrat", "darkcomet", "blackshades", "poison ivy", "quasar", "nanocore",
        "remcos", "asyncrat", "xworm", "dcrat", "venom", "pandora",
        # Ransomware
        "wannacry", "petya", "locky", "cerber", "cryptolocker", "ryuk", "revil",
        "sodinokibi", "dharma", "phobos", "stop", "djvu", "netwalker",
        # Keyloggers / Stealers
        "ardamax", "refog", "spyrix", "hawkeye", "pony", "formbook", "azorult",
        "redline", "vidar", "raccoon", "loki", "agent tesla",
        # Mineros
        "xmrig", "cpuminer", "sgminer", "cgminer", "nicehash", "coinminer",
        "minerd", "claymore",
        # Adware / PUPs
        "babylon", "conduit", "sweetpacks", "searchprotect", "mysearchdial",
        "istart123", "delta-homes", "qvo6", "mystartsearch",
        # Herramientas de hacking usadas como malware
        "mimikatz", "pwdump", "fgdump", "gsecdump", "wce", "lsadump",
        "pwconsole", "procdump", "ncrack", "hydra",
        # Backdoors / Bots
        "gh0st", "spyeye", "zeus", "citadel", "carberp", "torpig", "bredolab",
        "sality", "virut", "ramnit", "zeroaccess", "sirefef",
        # Grayware
        "bprotector", "trovi", "webdiscover", "trj", "windefend",
    }

    def scan_suspicious_processes(self):
        """Detecta procesos sospechosos en ejecucion comparando con lista de malware conocido"""
        result = {
            "suspicious": [],
            "high_cpu": [],
            "all_processes": [],
            "status": "BUENO",
        }
        try:
            for proc in psutil.process_iter(["pid", "name", "exe", "cpu_percent",
                                              "memory_percent", "username", "status"]):
                try:
                    info = proc.info
                    pname = (info.get("name") or "").lower()
                    pexe = (info.get("exe") or "").lower()

                    proc_entry = {
                        "pid": info.get("pid"),
                        "name": info.get("name", "Desconocido"),
                        "exe": info.get("exe") or "Desconocido",
                        "cpu": round(info.get("cpu_percent") or 0, 1),
                        "mem": round(info.get("memory_percent") or 0, 1),
                        "user": info.get("username") or "Desconocido",
                        "status": info.get("status", "?"),
                        "suspicious_reason": None,
                    }

                    # 1. Comparar con nombres de malware conocido
                    for malware_name in self.KNOWN_MALWARE_PROCESSES:
                        if malware_name in pname or malware_name in pexe:
                            proc_entry["suspicious_reason"] = f"Coincide con malware conocido: '{malware_name}'"
                            result["suspicious"].append(proc_entry)
                            result["status"] = "CRITICO"
                            break

                    # 2. Procesos sin ejecutable en disco (sospechoso)
                    if proc_entry["suspicious_reason"] is None:
                        exe_path = info.get("exe")
                        # Excepciones conocidas: pseudo-procesos del sistema sin exe real
                        allowed_no_exe = ["registry", "memcompression", "system", "system idle process"]
                        if exe_path and not os.path.exists(exe_path) and pname not in allowed_no_exe:
                            proc_entry["suspicious_reason"] = "Ejecutable no existe en disco"
                            result["suspicious"].append(proc_entry)
                            if result["status"] == "BUENO":
                                result["status"] = "ADVERTENCIA"

                    # 3. Proceso consumiendo >50% CPU (puede ser minero)
                    cpu_val = info.get("cpu_percent") or 0
                    if cpu_val > 50 and pname not in ["antimalware service executable", "msmpeng.exe"]:
                        proc_entry_copy = dict(proc_entry)
                        proc_entry_copy["reason"] = f"CPU muy alto: {cpu_val:.0f}%"
                        result["high_cpu"].append(proc_entry_copy)

                    result["all_processes"].append(proc_entry)

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            result["error"] = str(e)

        result["total"] = len(result["all_processes"])
        result["suspicious_count"] = len(result["suspicious"])
        return result

    def get_defender_threat_history(self):
        """Obtiene el historial de amenazas detectadas por Windows Defender"""
        threats = {"detected": [], "status": "BUENO", "message": ""}
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-MpThreatDetection | Select-Object -Property ThreatID, ActionSuccess, CurrentThreatExecutionStatusID, DetectionSourceTypeID, DomainUser, InitialDetectionTime, LastThreatStatusChangeTime, ProcessName, RemediationTime, Resources | ConvertTo-Json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0 and result.stdout and result.stdout.strip() != "null":
                try:
                    data = json.loads(result.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in (data or []):
                        threats["detected"].append({
                            "threat_id": item.get("ThreatID", "N/A"),
                            "process": item.get("ProcessName", "Desconocido"),
                            "time": str(item.get("InitialDetectionTime", "N/A")),
                            "remediated": bool(item.get("ActionSuccess", False)),
                            "resources": str(item.get("Resources", "N/A"))[:100],
                        })
                    count = len(threats["detected"])
                    threats["count"] = count
                    if count > 0:
                        not_remediated = sum(1 for t in threats["detected"] if not t["remediated"])
                        if not_remediated > 0:
                            threats["status"] = "CRITICO"
                            threats["message"] = f"{count} amenaza(s) detectadas, {not_remediated} sin remediar"
                        else:
                            threats["status"] = "ADVERTENCIA"
                            threats["message"] = f"{count} amenaza(s) detectadas y remediadas"
                    else:
                        threats["status"] = "BUENO"
                        threats["message"] = "Sin historial de amenazas detectadas"
                except:
                    threats["count"] = 0
                    threats["message"] = "Sin historial de amenazas"
            else:
                threats["count"] = 0
                threats["message"] = "Sin historial de amenazas detectadas"
        except Exception as e:
            threats["message"] = f"No se pudo obtener historial: {str(e)[:80]}"
            threats["count"] = -1
        return threats

    def trigger_defender_quick_scan(self, log_callback=None):
        """Dispara un escaneo rapido de Windows Defender"""
        try:
            if log_callback:
                log_callback("Iniciando escaneo rapido de Windows Defender...")
                log_callback("Esto puede tardar varios minutos.")
            result = subprocess.run(
                ["powershell", "-Command", "Start-MpScan -ScanType QuickScan"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                if log_callback:
                    log_callback("Escaneo completado exitosamente.")
                return {"success": True, "message": "Escaneo rapido completado"}
            else:
                err = result.stderr.strip()[:200]
                if log_callback:
                    log_callback(f"Error: {err}")
                return {"success": False, "message": err}
        except subprocess.TimeoutExpired:
            msg = "El escaneo tomo demasiado tiempo (> 5 min). Puede que siga corriendo en segundo plano."
            if log_callback:
                log_callback(msg)
            return {"success": False, "message": msg}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def check_suspicious_startup_malware(self, startup_items=None):
        """Verifica entradas de inicio contra lista de malware conocido.
        Acepta una lista de items ya obtenida, o los obtiene directamente si no se pasa.
        """
        # Si no se pasaron items externos, obtenerlos ahora
        if startup_items is None:
            startup = self.check_startup_programs()
            startup_items = startup.get("items", [])

        suspicious = []
        for item in startup_items:
            name_lower = item.get("name", "").lower()
            cmd_lower = item.get("command", "").lower()
            matched = False
            for malware_name in self.KNOWN_MALWARE_PROCESSES:
                if malware_name in name_lower or malware_name in cmd_lower:
                    suspicious.append({
                        "name": item.get("name"),
                        "command": item.get("command"),
                        "location": item.get("location"),
                        "reason": f"Coincide con malware conocido: '{malware_name}'",
                    })
                    matched = True
                    break
            # Detectar ejecutables desde carpetas temporales (muy sospechoso)
            if not matched:
                tmp_patterns = ["\\temp\\", "\\tmp\\", "\\appdata\\local\\temp\\"]
                if any(tmp in cmd_lower for tmp in tmp_patterns):
                    suspicious.append({
                        "name": item.get("name"),
                        "command": item.get("command"),
                        "location": item.get("location"),
                        "reason": "Se ejecuta desde carpeta TEMP (muy sospechoso)",
                    })
        return {
            "suspicious": suspicious,
            "count": len(suspicious),
            "status": "CRITICO" if suspicious else "BUENO",
            "total_checked": len(startup_items),
        }

    def check_suspicious_network_connections(self):
        """Verifica conexiones de red activas en busca de puertos y IPs sospechosas"""
        result = {"connections": [], "suspicious": [], "status": "BUENO"}

        # Puertos tipicamente usados por malware/RATs
        SUSPICIOUS_PORTS = {
            1080: "SOCKS Proxy / Malware",
            1337: "Malware/Hacking",
            4444: "Metasploit default",
            5555: "Android debug / RAT",
            6666: "IRC Bot",
            6667: "IRC Bot",
            8080: "Proxy alternativo",
            9001: "Tor Network",
            9050: "Tor SOCKS",
            9051: "Tor Control",
            31337: "Back Orifice RAT",
            12345: "NetBus RAT",
            27374: "Sub7 Trojan",
            65535: "Puerto maximo (sospechoso)",
        }

        try:
            connections = psutil.net_connections(kind="inet")
            for conn in connections:
                if conn.status != psutil.CONN_ESTABLISHED:
                    continue
                raddr = conn.raddr
                if not raddr:
                    continue

                # Obtener nombre del proceso
                proc_name = "Desconocido"
                try:
                    if conn.pid:
                        p = psutil.Process(conn.pid)
                        proc_name = p.name()
                except:
                    pass

                conn_info = {
                    "pid": conn.pid,
                    "process": proc_name,
                    "local_ip": conn.laddr.ip if conn.laddr else "?",
                    "local_port": conn.laddr.port if conn.laddr else 0,
                    "remote_ip": raddr.ip,
                    "remote_port": raddr.port,
                    "status": conn.status,
                    "suspicious_reason": None,
                }

                # Verificar puerto remoto sospechoso
                if raddr.port in SUSPICIOUS_PORTS:
                    conn_info["suspicious_reason"] = f"Puerto sospechoso: {raddr.port} ({SUSPICIOUS_PORTS[raddr.port]})"
                    result["suspicious"].append(conn_info)
                    result["status"] = "ADVERTENCIA"

                # IPs de loopback o locales no son sospechosas
                elif not raddr.ip.startswith(("127.", "192.168.", "10.", "172.", "::1")):
                    result["connections"].append(conn_info)

        except Exception as e:
            result["error"] = str(e)

        result["total"] = len(result["connections"]) + len(result["suspicious"])
        return result

    def search_malware_online(self, process_name, log_callback=None):
        """Busca informacion de un proceso en buscadores de malware online"""
        search_urls = [
            ("ProcessLibrary", f"https://www.processlibrary.com/en/search/?q={process_name}"),
            ("Should I Remove It", f"https://www.shouldiremoveit.com/search.aspx?q={process_name}"),
            ("VirusTotal Files", f"https://www.virustotal.com/gui/search/{process_name}"),
        ]
        try:
            import webbrowser
            for site_name, url in search_urls:
                if log_callback:
                    log_callback(f"Abriendo {site_name}: {url}")
                webbrowser.open(url)
        except Exception as e:
            if log_callback:
                log_callback(f"Error: {e}")
        return search_urls

    def generate_html_report(self, all_data, filepath=None):
        """Generar reporte HTML completo"""
        if not filepath:
            filepath = os.path.join(
                os.path.expanduser("~"), "Desktop",
                f"PC_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            )

        system = all_data.get("system", {})
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reporte de PC - {timestamp}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #0d1117; color: #e6edf3; padding: 20px; }}
  h1 {{ color: #58a6ff; text-align: center; margin-bottom: 10px; font-size: 2em; }}
  .subtitle {{ text-align: center; color: #8b949e; margin-bottom: 30px; }}
  .section {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px; padding: 20px; margin-bottom: 20px; }}
  .section h2 {{ color: #58a6ff; margin-bottom: 15px; font-size: 1.2em; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.85em; font-weight: bold; }}
  .badge-BUENO {{ background: #196c2e; color: #3fb950; }}
  .badge-ADVERTENCIA {{ background: #9e6a03; color: #e3b341; }}
  .badge-CRITICO {{ background: #da3633; color: #ff8080; }}
  .badge-INFO {{ background: #0d419d; color: #58a6ff; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  th {{ background: #1c2128; color: #8b949e; text-align: left; padding: 8px 12px; font-size: 0.9em; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #21262d; font-size: 0.9em; }}
  tr:hover td {{ background: #1c2128; }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
  .stat-card {{ background: #1c2128; border-radius: 8px; padding: 15px; }}
  .stat-value {{ font-size: 1.8em; font-weight: bold; color: #58a6ff; }}
  .stat-label {{ color: #8b949e; font-size: 0.85em; margin-top: 5px; }}
  .footer {{ text-align: center; color: #8b949e; margin-top: 30px; font-size: 0.85em; }}
  .progress-bar {{ background: #21262d; border-radius: 4px; height: 8px; margin-top: 5px; }}
  .progress-fill {{ height: 100%; border-radius: 4px; }}
</style>
</head>
<body>
<h1>PC Examiner Pro - Reporte de Diagnostico</h1>
<p class="subtitle">Generado: {timestamp} | Host: {system.get("hostname", "Desconocido")}</p>
"""

        # Información del sistema
        html_content += """<div class="section">
<h2>Informacion del Sistema</h2>
<div class="stat-grid">"""
        if system:
            items = [
                ("Sistema Operativo", system.get("os", "N/A")),
                ("Procesador", system.get("processor", "N/A")[:50]),
                ("Hostname", system.get("hostname", "N/A")),
                ("Tiempo activo", system.get("uptime", "N/A")),
                ("Ultimo inicio", system.get("boot_time", "N/A")),
            ]
            for label, value in items:
                html_content += f"""<div class="stat-card">
<div class="stat-label">{label}</div>
<div style="font-size:1em; margin-top:5px; color:#e6edf3;">{value}</div>
</div>"""
        html_content += "</div></div>"

        # Discos
        disks = all_data.get("disks", [])
        html_content += """<div class="section"><h2>Estado de los Discos</h2>"""
        if disks:
            html_content += "<table><tr><th>Unidad</th><th>Sistema Arch.</th><th>Total</th><th>Usado</th><th>Libre</th><th>Uso</th><th>Estado</th></tr>"
            for disk in disks:
                if "error" not in disk:
                    pct = disk.get("percent", 0)
                    color = "#3fb950" if pct < 75 else ("#e3b341" if pct < 90 else "#ff4444")
                    status_class = disk.get("status","INFO").replace("Í","I").replace("É","E")
                    html_content += f"""<tr>
<td>{disk.get("mountpoint","N/A")}</td>
<td>{disk.get("fstype","N/A")}</td>
<td>{disk.get("total_gb","N/A")} GB</td>
<td>{disk.get("used_gb","N/A")} GB</td>
<td>{disk.get("free_gb","N/A")} GB</td>
<td><span>{pct}%</span><div class="progress-bar"><div class="progress-fill" style="width:{pct}%; background:{color};"></div></div></td>
<td><span class="badge badge-{status_class}">{disk.get("status","INFO")}</span></td>
</tr>"""
            html_content += "</table>"
        html_content += "</div>"

        # CPU / RAM
        cpu_ram = all_data.get("cpu_ram", {})
        if cpu_ram:
            html_content += f"""<div class="section">
<h2>CPU y Memoria RAM</h2>
<div class="stat-grid">
<div class="stat-card"><div class="stat-value">{cpu_ram.get("cpu_percent_avg","N/A")}%</div><div class="stat-label">Uso promedio CPU</div></div>
<div class="stat-card"><div class="stat-value">{cpu_ram.get("ram_percent","N/A")}%</div><div class="stat-label">Uso RAM ({cpu_ram.get("ram_used_gb","N/A")} / {cpu_ram.get("ram_total_gb","N/A")} GB)</div></div>
<div class="stat-card"><div class="stat-value">{cpu_ram.get("cpu_cores","N/A")}</div><div class="stat-label">Nucleos fisicos ({cpu_ram.get("cpu_threads","N/A")} hilos)</div></div>
<div class="stat-card"><div class="stat-value">{cpu_ram.get("cpu_freq_mhz","N/A")} MHz</div><div class="stat-label">Frecuencia CPU actual</div></div>
</div></div>"""

        # Seguridad
        security = all_data.get("security", {})
        if security.get("checks"):
            html_content += """<div class="section"><h2>Seguridad</h2>
<table><tr><th>Verificacion</th><th>Estado</th><th>Valor</th></tr>"""
            for check in security["checks"]:
                sc = check["status"].replace("Í","I").replace("É","E")
                html_content += f"""<tr>
<td>{check["name"]}</td>
<td><span class="badge badge-{sc}">{check["status"]}</span></td>
<td>{check["value"]}</td>
</tr>"""
            html_content += "</table></div>"

        # Archivos temporales
        temp = all_data.get("temp_files", {})
        if temp:
            html_content += f"""<div class="section">
<h2>Archivos Temporales</h2>
<p style="margin-bottom:10px;">Total detectado: <strong style="color:#e3b341;">{temp.get("total_gb","0")} GB ({temp.get("total_mb","0")} MB)</strong></p>"""
            if temp.get("locations"):
                html_content += "<table><tr><th>Ubicacion</th><th>Tamano</th></tr>"
                for loc in temp["locations"]:
                    html_content += f"<tr><td>{loc['name']}</td><td>{loc['size_mb']} MB</td></tr>"
                html_content += "</table>"
            html_content += "</div>"

        # Red
        net = all_data.get("network", {})
        if net:
            html_content += """<div class="section"><h2>Conectividad de Red</h2>"""
            if net.get("ping_results"):
                html_content += "<table><tr><th>Servidor</th><th>IP</th><th>Latencia</th><th>Estado</th></tr>"
                for ping in net["ping_results"]:
                    sc = ping["status"].replace("Í","I").replace("É","E")
                    html_content += f"""<tr>
<td>{ping["target"]}</td>
<td>{ping["ip"]}</td>
<td>{ping["avg_ms"]} ms</td>
<td><span class="badge badge-{sc}">{ping["status"]}</span></td>
</tr>"""
                html_content += "</table>"
            html_content += "</div>"

        # Programas de inicio
        startup = all_data.get("startup", {})
        if startup:
            items = startup.get("items", [])
            html_content += f"""<div class="section">
<h2>Programas de Inicio ({len(items)} encontrados)</h2>"""
            if items:
                html_content += "<table><tr><th>Nombre</th><th>Comando</th><th>Ubicacion</th></tr>"
                for item in items[:30]:
                    cmd = item.get("command","")
                    if len(cmd) > 80:
                        cmd = cmd[:80] + "..."
                    html_content += f"<tr><td>{item.get('name','N/A')}</td><td style='font-size:0.8em;'>{cmd}</td><td>{item.get('location','N/A')}</td></tr>"
                html_content += "</table>"
            html_content += "</div>"

        html_content += f"""
<div class="footer">
  <p>Generado por PC Examiner Pro | {timestamp}</p>
  <p>Reporte de diagnostico del sistema</p>
</div>
</body>
</html>"""

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        return filepath


# ─────────────────────────────────────────────
# WIDGETS PERSONALIZADOS
# ─────────────────────────────────────────────

class StatusBadge(ctk.CTkLabel):
    def __init__(self, master, status="INFO", **kwargs):
        color = STATUS_COLORS.get(status, "#8b949e")
        super().__init__(
            master,
            text=f"  {status}  ",
            text_color=color,
            fg_color=self._get_bg(status),
            corner_radius=8,
            font=ctk.CTkFont(size=11, weight="bold"),
            **kwargs
        )

    def _get_bg(self, status):
        bg_map = {
            "BUENO": "#1a3a24",
            "ADVERTENCIA": "#3d2e0a",
            "CRÍTICO": "#3d1a1a",
            "INFO": "#0d2a5a",
            "DESCONOCIDO": "#2a2a2a",
        }
        return bg_map.get(status, "#2a2a2a")


class StatCard(ctk.CTkFrame):
    """Tarjeta de estadística"""
    def __init__(self, master, title, value, subtitle="", icon="📊", status=None, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=12,
                        border_width=1, border_color=COLORS["border"], **kwargs)

        # Icon + title
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 0))
        ctk.CTkLabel(header, text=icon, font=ctk.CTkFont(size=20)).pack(side="left")
        ctk.CTkLabel(header, text=title, font=ctk.CTkFont(size=12),
                    text_color=COLORS["text_secondary"]).pack(side="left", padx=8)

        # Value
        ctk.CTkLabel(self, text=str(value),
                    font=ctk.CTkFont(size=28, weight="bold"),
                    text_color=COLORS["accent_blue"]).pack(padx=15, pady=(5, 0))

        # Subtitle / status
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=15, pady=(0, 12))
        if subtitle:
            ctk.CTkLabel(bottom, text=subtitle, font=ctk.CTkFont(size=11),
                        text_color=COLORS["text_secondary"]).pack(side="left")
        if status:
            StatusBadge(bottom, status=status).pack(side="right")


# ─────────────────────────────────────────────
# VENTANA PRINCIPAL
# ─────────────────────────────────────────────

class PCExaminerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.engine = DiagnosticEngine()
        self.all_data = {}
        self.scan_complete = False
        self._setup_window()
        self._build_ui()
        # Iniciar escaneo automáticamente
        self.after(500, self.run_full_scan)

    def _setup_window(self):
        self.title("PC Examiner Pro")
        self.geometry("1280x800")
        self.minsize(1100, 700)
        self.configure(fg_color=COLORS["bg_dark"])
        try:
            self.state("zoomed")
        except:
            pass

    def _build_ui(self):
        # ── SIDEBAR ──
        self.sidebar = ctk.CTkFrame(self, fg_color=COLORS["bg_card"],
                                    corner_radius=0, width=220,
                                    border_width=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo / título
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(fill="x", padx=15, pady=(20, 10))
        ctk.CTkLabel(logo_frame, text="PC", font=ctk.CTkFont(size=36, weight="bold"),
                    text_color=COLORS["accent_blue"]).pack()
        ctk.CTkLabel(logo_frame, text="Examiner Pro",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color=COLORS["text_primary"]).pack()

        # Separador
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=15, pady=10)

        # Botones de navegación
        self.nav_buttons = {}
        nav_items = [
            ("dashboard", "  Dashboard", self.show_dashboard),
            ("discos", "  Discos", self.show_disks),
            ("cpu_ram", "  CPU / RAM", self.show_cpu_ram),
            ("temperatura", "  Temperatura", self.show_temperature),
            ("bateria", "  Bateria", self.show_battery),
            ("limpieza", "  Limpieza", self.show_cleanup),
            ("inicio", "  Inicio", self.show_startup),
            ("drivers", "  Drivers", self.show_drivers),
            ("seguridad", "  Seguridad", self.show_security),
            ("red", "  Red", self.show_network),
            ("actualizaciones", "  Actualizaciones", self.show_updates),
        ]

        for key, label, command in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=label,
                anchor="w", font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=COLORS["bg_card2"],
                text_color=COLORS["text_secondary"],
                corner_radius=8, height=40,
                command=command
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = btn

        # Separador
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=15, pady=10)

        # Botón Escanear
        self.scan_btn = ctk.CTkButton(
            self.sidebar, text="Escanear PC",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent_blue"],
            hover_color="#1a7fe0",
            corner_radius=8, height=42,
            command=self.run_full_scan
        )
        self.scan_btn.pack(fill="x", padx=10, pady=4)

        # Botón Reporte
        self.report_btn = ctk.CTkButton(
            self.sidebar, text="Exportar Reporte HTML",
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["bg_card2"],
            hover_color=COLORS["border"],
            corner_radius=8, height=42,
            command=self.export_report
        )
        self.report_btn.pack(fill="x", padx=10, pady=4)

        # Status del último escaneo
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"]).pack(fill="x", padx=15, pady=10)
        self.last_scan_label = ctk.CTkLabel(
            self.sidebar, text="Ultimo escaneo:\nNunca",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_secondary"]
        )
        self.last_scan_label.pack(padx=15, pady=5)

        # ── ÁREA PRINCIPAL ──
        self.main_area = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], corner_radius=0)
        self.main_area.pack(side="right", fill="both", expand=True)

        # Header
        self.header = ctk.CTkFrame(self.main_area, fg_color=COLORS["bg_card"],
                                   height=60, corner_radius=0)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.page_title = ctk.CTkLabel(
            self.header, text="Dashboard",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        self.page_title.pack(side="left", padx=25, pady=15)

        # Barra de progreso del escaneo
        self.progress_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        self.progress_frame.pack(side="right", padx=20, pady=10)
        self.progress_label = ctk.CTkLabel(
            self.progress_frame, text="Escaneando...",
            font=ctk.CTkFont(size=12), text_color=COLORS["accent_blue"]
        )
        self.progress_label.pack()
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, width=200, height=6)
        self.progress_bar.pack(pady=2)
        self.progress_bar.set(0)

        # Contenido principal (scrollable)
        self.content_frame = ctk.CTkScrollableFrame(
            self.main_area, fg_color=COLORS["bg_dark"],
            scrollbar_button_color=COLORS["border"]
        )
        self.content_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Página actual
        self.current_page = "dashboard"
        self._activate_nav("dashboard")

        # Mostrar loading inicial
        self._show_loading()

    def _show_loading(self):
        """Mostrar pantalla de carga"""
        self._clear_content()
        frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        frame.pack(expand=True, pady=80)
        ctk.CTkLabel(frame, text="Analizando tu PC...",
                    font=ctk.CTkFont(size=22, weight="bold"),
                    text_color=COLORS["accent_blue"]).pack(pady=10)
        ctk.CTkLabel(frame, text="Recopilando informacion del sistema. Por favor espera.",
                    font=ctk.CTkFont(size=14),
                    text_color=COLORS["text_secondary"]).pack()

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _activate_nav(self, key):
        for k, btn in self.nav_buttons.items():
            if k == key:
                btn.configure(
                    fg_color=COLORS["bg_card2"],
                    text_color=COLORS["accent_blue"]
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_secondary"]
                )
        self.current_page = key

    # ── ESCANEO ──
    def run_full_scan(self):
        self.scan_btn.configure(state="disabled", text="Escaneando...")
        self.progress_bar.set(0)
        self.progress_label.configure(text="Iniciando escaneo...")
        self._show_loading()

        def scan_thread():
            steps = [
                ("Sistema", self.engine.get_system_info, "system", 0.08),
                ("Discos", self.engine.check_disk_health, "disks", 0.18),
                ("CPU/RAM", self.engine.check_cpu_ram, "cpu_ram", 0.28),
                ("Temperatura", self.engine.check_temperatures, "temperatures", 0.36),
                ("Bateria", self.engine.check_battery, "battery", 0.44),
                ("Arch. Temporales", self.engine.check_temp_files, "temp_files", 0.52),
                ("Inicio", self.engine.check_startup_programs, "startup", 0.60),
                ("Drivers", self.engine.check_drivers, "drivers", 0.70),
                ("Seguridad", self.engine.check_security, "security", 0.80),
                ("Red", self.engine.check_network, "network", 0.88),
                ("Actualizaciones", self.engine.check_windows_updates, "updates", 1.00),
            ]

            for step_name, func, key, progress in steps:
                self.after(0, lambda p=progress, n=step_name: (
                    self.progress_bar.set(p),
                    self.progress_label.configure(text=f"Verificando {n}...")
                ))
                try:
                    self.all_data[key] = func()
                except Exception as e:
                    self.all_data[key] = {"error": str(e)}

            self.after(0, self._scan_complete)

        threading.Thread(target=scan_thread, daemon=True).start()

    def _scan_complete(self):
        self.scan_complete = True
        self.scan_btn.configure(state="normal", text="Escanear PC")
        self.progress_bar.set(1.0)
        self.progress_label.configure(text="Escaneo completo")
        self.last_scan_label.configure(
            text=f"Ultimo escaneo:\n{datetime.datetime.now().strftime('%H:%M:%S')}"
        )
        self.show_dashboard()

    # ── PÁGINAS ──
    def show_dashboard(self):
        self._activate_nav("dashboard")
        self.page_title.configure(text="Dashboard General")
        self._clear_content()

        if not self.scan_complete:
            self._show_loading()
            return

        # Calcular estado general
        statuses = []
        checks = [
            ("cpu_ram", "cpu_status"),
            ("cpu_ram", "ram_status"),
            ("battery", "status"),
            ("startup", "status"),
            ("security", "status"),
        ]
        for section, key in checks:
            data = self.all_data.get(section, {})
            if isinstance(data, dict):
                statuses.append(data.get(key, "BUENO"))

        disks = self.all_data.get("disks", [])
        if isinstance(disks, list):
            for d in disks:
                statuses.append(d.get("status", "BUENO"))

        overall = "BUENO"
        if "CRÍTICO" in statuses:
            overall = "CRÍTICO"
        elif "ADVERTENCIA" in statuses:
            overall = "ADVERTENCIA"

        # Banner de estado general
        banner_color = {"BUENO": "#196c2e", "ADVERTENCIA": "#3d2e0a", "CRÍTICO": "#3d1a1a"}.get(overall, "#1c2128")
        banner = ctk.CTkFrame(self.content_frame, fg_color=banner_color, corner_radius=12)
        banner.pack(fill="x", pady=(0, 15))

        icons = {"BUENO": "OK", "ADVERTENCIA": "ATENCION", "CRÍTICO": "CRITICO"}
        texts = {
            "BUENO": "Tu PC esta en buen estado",
            "ADVERTENCIA": "Se detectaron advertencias en tu PC",
            "CRÍTICO": "Se detectaron problemas criticos en tu PC"
        }
        ctk.CTkLabel(banner, text=f"{icons.get(overall,'INFO')} — {texts.get(overall,'Estado desconocido')}",
                    font=ctk.CTkFont(size=18, weight="bold"),
                    text_color=STATUS_COLORS.get(overall, "#ffffff")).pack(padx=20, pady=15)

        # Cards de resumen rápido
        cards_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        cards_frame.pack(fill="x", pady=(0, 15))
        for i in range(4):
            cards_frame.columnconfigure(i, weight=1)

        cpu_ram = self.all_data.get("cpu_ram", {})
        temp_files = self.all_data.get("temp_files", {})

        disk_free = "N/A"
        disk_status = "BUENO"
        if disks and isinstance(disks, list) and disks:
            d = disks[0]
            disk_free = f"{d.get('free_gb','?')} GB"
            disk_status = d.get("status", "BUENO")

        summary_cards = [
            ("CPU", f"{cpu_ram.get('cpu_percent_avg','?')}%",
             f"{cpu_ram.get('cpu_cores','?')} nucleos", "CPU", cpu_ram.get("cpu_status","BUENO")),
            ("RAM", f"{cpu_ram.get('ram_percent','?')}%",
             f"{cpu_ram.get('ram_used_gb','?')}/{cpu_ram.get('ram_total_gb','?')} GB", "RAM", cpu_ram.get("ram_status","BUENO")),
            ("Disco libre", disk_free, "Primer disco", "DISK", disk_status),
            ("Temp. basura", f"{temp_files.get('total_gb','?')} GB",
             "Archivos temporales", "TEMP", temp_files.get("status","BUENO")),
        ]

        for i, (title, value, subtitle, icon, status) in enumerate(summary_cards):
            card = StatCard(cards_frame, title=title, value=value,
                          subtitle=subtitle, icon=icon, status=status)
            card.grid(row=0, column=i, padx=6, pady=6, sticky="nsew")

        # Resumen por sección
        ctk.CTkLabel(self.content_frame, text="Resumen por seccion",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(anchor="w", pady=(10, 8))

        sections_data = [
            ("Discos", self._get_disk_summary()),
            ("Temperatura", self._get_temp_summary()),
            ("Bateria", self._get_battery_summary()),
            ("Inicio", self._get_startup_summary()),
            ("Seguridad", self._get_security_summary()),
            ("Red", self._get_network_summary()),
            ("Actualizaciones", self._get_updates_summary()),
            ("Drivers", self._get_drivers_summary()),
        ]

        grid_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        grid_frame.pack(fill="x")
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.columnconfigure(1, weight=1)

        for i, (title, (status, msg)) in enumerate(sections_data):
            row = i // 2
            col = i % 2
            card = ctk.CTkFrame(grid_frame, fg_color=COLORS["bg_card"],
                               corner_radius=10, border_width=1,
                               border_color=COLORS["border"])
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=15, pady=12)
            ctk.CTkLabel(inner, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(side="left")
            StatusBadge(inner, status=status).pack(side="right")
            ctk.CTkLabel(card, text=msg, font=ctk.CTkFont(size=11),
                        text_color=COLORS["text_secondary"],
                        wraplength=350).pack(anchor="w", padx=15, pady=(0, 12))

    def _get_disk_summary(self):
        disks = self.all_data.get("disks", [])
        if not disks:
            return ("DESCONOCIDO", "No se pudo obtener informacion")
        worst = "BUENO"
        msgs = []
        for d in disks:
            if isinstance(d, dict) and "error" not in d:
                s = d.get("status", "BUENO")
                msgs.append(f"{d.get('mountpoint','?')}: {d.get('percent','?')}% usado")
                if s == "CRÍTICO": worst = "CRÍTICO"
                elif s == "ADVERTENCIA" and worst != "CRÍTICO": worst = "ADVERTENCIA"
        return (worst, " | ".join(msgs[:3]))

    def _get_temp_summary(self):
        temps = self.all_data.get("temperatures", {})
        if not temps or "info" in temps:
            return ("INFO", "Temperatura no disponible en este sistema")
        worst = "BUENO"
        max_temp = 0
        for name, entries in temps.items():
            for e in entries:
                if e.get("current", 0) > max_temp:
                    max_temp = e["current"]
                s = e.get("status", "BUENO")
                if s == "CRÍTICO": worst = "CRÍTICO"
                elif s == "ADVERTENCIA" and worst != "CRÍTICO": worst = "ADVERTENCIA"
        return (worst, f"Temperatura maxima detectada: {max_temp} C" if max_temp > 0 else "Sin datos de temperatura")

    def _get_battery_summary(self):
        battery = self.all_data.get("battery", {})
        if not battery.get("available"):
            return ("INFO", "Sin bateria (PC de escritorio o no detectada)")
        pct = battery.get("percent", 0)
        return (battery.get("status", "BUENO"), f"Carga: {pct}% | {battery.get('time_left','N/A')}")

    def _get_startup_summary(self):
        startup = self.all_data.get("startup", {})
        count = startup.get("count", 0)
        return (startup.get("status", "BUENO"), f"{count} programas de inicio detectados")

    def _get_security_summary(self):
        security = self.all_data.get("security", {})
        status = security.get("status", "INFO")
        checks = security.get("checks", [])
        problems = [c for c in checks if c.get("status") in ["CRÍTICO", "ADVERTENCIA"]]
        if problems:
            return (status, f"{len(problems)} problema(s) de seguridad detectado(s)")
        return (status, "Sin problemas de seguridad detectados")

    def _get_network_summary(self):
        net = self.all_data.get("network", {})
        pings = net.get("ping_results", [])
        if not pings:
            return ("INFO", "Sin datos de red")
        ok = all(p.get("status") == "BUENO" for p in pings)
        return ("BUENO" if ok else "ADVERTENCIA",
                " | ".join([f"{p['target']}: {p['avg_ms']} ms" for p in pings]))

    def _get_updates_summary(self):
        updates = self.all_data.get("updates", {})
        return (updates.get("status", "INFO"), updates.get("message", "No verificado"))

    def _get_drivers_summary(self):
        drivers = self.all_data.get("drivers", {})
        return (drivers.get("status", "INFO"), drivers.get("message", "No verificado"))

    # ── PÁGINA DISCOS ──
    def show_disks(self):
        self._activate_nav("discos")
        self.page_title.configure(text="Estado de los Discos")
        self._clear_content()

        disks = self.all_data.get("disks", [])
        if not disks:
            ctk.CTkLabel(self.content_frame, text="No se encontro informacion de discos",
                        text_color=COLORS["text_secondary"]).pack(pady=50)
            return

        for disk in disks:
            if "error" in disk:
                continue
            card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
            card.pack(fill="x", pady=8)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=20, pady=(15, 5))

            ctk.CTkLabel(header, text=f"Disco: {disk.get('mountpoint','?')} — {disk.get('device','?')}",
                        font=ctk.CTkFont(size=15, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(side="left")
            StatusBadge(header, status=disk.get("status", "BUENO")).pack(side="right")

            if "model" in disk:
                ctk.CTkLabel(card, text=f"Modelo: {disk['model']} | Interfaz: {disk.get('interface','N/A')}",
                            font=ctk.CTkFont(size=11), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=20)

            # Barra de progreso
            pct = disk.get("percent", 0)
            ctk.CTkLabel(card, text=f"Uso: {pct}%",
                        font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=20, pady=(10,0))

            prog_color = COLORS["accent_green"] if pct < 75 else (COLORS["accent_yellow"] if pct < 90 else COLORS["accent_red"])
            prog_bar = ctk.CTkProgressBar(card, height=10, progress_color=prog_color)
            prog_bar.pack(fill="x", padx=20, pady=(5, 10))
            prog_bar.set(pct / 100)

            # Stats
            stats_frame = ctk.CTkFrame(card, fg_color="transparent")
            stats_frame.pack(fill="x", padx=20, pady=(0, 15))

            stats = [
                ("Total", f"{disk.get('total_gb','?')} GB"),
                ("Usado", f"{disk.get('used_gb','?')} GB"),
                ("Libre", f"{disk.get('free_gb','?')} GB"),
                ("FS", disk.get("fstype", "N/A")),
            ]
            for label, value in stats:
                item = ctk.CTkFrame(stats_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
                item.pack(side="left", padx=5)
                ctk.CTkLabel(item, text=value,
                            font=ctk.CTkFont(size=14, weight="bold"),
                            text_color=COLORS["accent_blue"]).pack(padx=12, pady=(6, 0))
                ctk.CTkLabel(item, text=label,
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["text_secondary"]).pack(padx=12, pady=(0, 6))

    # ── PÁGINA CPU/RAM ──
    def show_cpu_ram(self):
        self._activate_nav("cpu_ram")
        self.page_title.configure(text="CPU y Memoria RAM")
        self._clear_content()

        data = self.all_data.get("cpu_ram", {})
        if not data:
            ctk.CTkLabel(self.content_frame, text="No se pudo obtener datos de CPU/RAM",
                        text_color=COLORS["text_secondary"]).pack(pady=50)
            return

        # Cards principales
        top_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        top_frame.pack(fill="x", pady=(0, 15))
        for i in range(4):
            top_frame.columnconfigure(i, weight=1)

        main_stats = [
            ("CPU Promedio", f"{data.get('cpu_percent_avg','?')}%", f"{data.get('cpu_cores','?')} nucleos fisicos", "CPU", data.get("cpu_status","BUENO")),
            ("RAM Usada", f"{data.get('ram_percent','?')}%", f"{data.get('ram_used_gb','?')} / {data.get('ram_total_gb','?')} GB", "RAM", data.get("ram_status","BUENO")),
            ("Frecuencia CPU", f"{data.get('cpu_freq_mhz','N/A')} MHz", f"Max: {data.get('cpu_freq_max_mhz','N/A')} MHz", "FREQ", "INFO"),
            ("Hilos", f"{data.get('cpu_threads','?')}", f"{data.get('cpu_cores','?')} nucleos fisicos", "THR", "INFO"),
        ]

        for i, (title, value, subtitle, icon, status) in enumerate(main_stats):
            card = StatCard(top_frame, title=title, value=value,
                          subtitle=subtitle, icon=icon, status=status)
            card.grid(row=0, column=i, padx=6, pady=6, sticky="nsew")

        # Uso por núcleo
        per_core = data.get("cpu_percent_per_core", [])
        if per_core:
            section = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                  corner_radius=12, border_width=1,
                                  border_color=COLORS["border"])
            section.pack(fill="x", pady=8)
            ctk.CTkLabel(section, text="Uso por nucleo de CPU",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

            cores_frame = ctk.CTkFrame(section, fg_color="transparent")
            cores_frame.pack(fill="x", padx=20, pady=(0, 15))

            cols = min(8, len(per_core))
            for i, pct in enumerate(per_core):
                col = i % cols
                row = i // cols
                core_frame = ctk.CTkFrame(cores_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
                core_frame.grid(row=row, column=col, padx=4, pady=4)
                ctk.CTkLabel(core_frame, text=f"#{i}",
                            font=ctk.CTkFont(size=10), text_color=COLORS["text_secondary"]).pack(padx=10, pady=(5, 0))
                color = COLORS["accent_green"] if pct < 50 else (COLORS["accent_yellow"] if pct < 80 else COLORS["accent_red"])
                pb = ctk.CTkProgressBar(core_frame, width=60, height=6, progress_color=color)
                pb.pack(padx=10, pady=2)
                pb.set(pct / 100)
                ctk.CTkLabel(core_frame, text=f"{pct:.0f}%",
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color=color).pack(padx=10, pady=(0, 5))

        # RAM detallada
        ram_section = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                   corner_radius=12, border_width=1,
                                   border_color=COLORS["border"])
        ram_section.pack(fill="x", pady=8)
        ctk.CTkLabel(ram_section, text="Detalle de Memoria",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

        ram_details = [
            ("Total", f"{data.get('ram_total_gb','?')} GB"),
            ("Usada", f"{data.get('ram_used_gb','?')} GB"),
            ("Disponible", f"{data.get('ram_available_gb','?')} GB"),
            ("Swap Total", f"{data.get('swap_total_gb','?')} GB"),
            ("Swap Usado", f"{data.get('swap_used_gb','?')} GB"),
        ]

        ram_grid = ctk.CTkFrame(ram_section, fg_color="transparent")
        ram_grid.pack(fill="x", padx=20, pady=(0, 15))
        for i, (label, value) in enumerate(ram_details):
            item = ctk.CTkFrame(ram_grid, fg_color=COLORS["bg_card2"], corner_radius=8)
            item.grid(row=0, column=i, padx=5, pady=5)
            ctk.CTkLabel(item, text=value,
                        font=ctk.CTkFont(size=15, weight="bold"),
                        text_color=COLORS["accent_blue"]).pack(padx=12, pady=(8, 0))
            ctk.CTkLabel(item, text=label,
                        font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(padx=12, pady=(0, 8))

    # ── PÁGINA TEMPERATURA ──
    def show_temperature(self):
        self._activate_nav("temperatura")
        self.page_title.configure(text="Temperatura del Sistema")
        self._clear_content()

        temps = self.all_data.get("temperatures", {})

        if not temps or "info" in temps:
            card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
            card.pack(fill="x", pady=20)
            ctk.CTkLabel(card, text="Monitoreo de temperatura no disponible",
                        font=ctk.CTkFont(size=16, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(pady=(20, 5))
            ctk.CTkLabel(card, text=(
                "Windows generalmente no expone sensores de temperatura directamente.\n"
                "Para datos de temperatura, instala HWMonitor, HWiNFO64 o Open Hardware Monitor."
            ), font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"],
            wraplength=500).pack(padx=20, pady=(5, 20))

            # Tips
            tips_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                     corner_radius=12, border_width=1,
                                     border_color=COLORS["border"])
            tips_card.pack(fill="x", pady=8)
            ctk.CTkLabel(tips_card, text="Consejos para controlar temperatura",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))
            tips = [
                "Limpiar el polvo interno de la laptop (especialmente los ventiladores)",
                "Temperaturas normales: CPU < 70 C en carga, < 50 C en reposo",
                "Temperatura critica: CPU > 90 C (puede causar throttling y danos)",
                "Considerar reemplazar la pasta termica si la laptop tiene +3 anos",
                "Usar superficies duras para que no se bloqueen las salidas de aire",
                "En juegos o carga alta, usar base de refrigeracion externa",
            ]
            for tip in tips:
                ctk.CTkLabel(tips_card, text=f"• {tip}", font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_secondary"]).pack(anchor="w", padx=25, pady=3)
            ctk.CTkLabel(tips_card, text="").pack(pady=5)
            return

        for sensor_name, entries in temps.items():
            card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
            card.pack(fill="x", pady=8)
            ctk.CTkLabel(card, text=f"Sensor: {sensor_name}",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

            for entry in entries:
                row = ctk.CTkFrame(card, fg_color=COLORS["bg_card2"], corner_radius=8)
                row.pack(fill="x", padx=20, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=12, pady=8)
                ctk.CTkLabel(inner, text=entry.get("label", sensor_name),
                            font=ctk.CTkFont(size=12)).pack(side="left")
                temp_val = entry.get("current", 0)
                color = COLORS["accent_green"] if temp_val < 70 else (
                    COLORS["accent_yellow"] if temp_val < 85 else COLORS["accent_red"])
                ctk.CTkLabel(inner, text=f"{temp_val} C",
                            font=ctk.CTkFont(size=14, weight="bold"),
                            text_color=color).pack(side="right", padx=10)
                StatusBadge(inner, status=entry.get("status", "BUENO")).pack(side="right")

            ctk.CTkLabel(card, text="").pack(pady=5)

    # ── PÁGINA BATERÍA ──
    def show_battery(self):
        self._activate_nav("bateria")
        self.page_title.configure(text="Estado de la Bateria")
        self._clear_content()

        battery = self.all_data.get("battery", {})

        if not battery.get("available"):
            card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
            card.pack(fill="x", pady=20)
            ctk.CTkLabel(card, text="No se detecto bateria",
                        font=ctk.CTkFont(size=16, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(pady=(20, 5))
            ctk.CTkLabel(card, text=battery.get("message", "Este equipo puede ser de escritorio"),
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_secondary"]).pack(pady=(5, 20))
            return

        # Card principal
        main_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        main_card.pack(fill="x", pady=8)

        header = ctk.CTkFrame(main_card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text=f"Bateria: {battery.get('name','Bateria')}",
                    font=ctk.CTkFont(size=16, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=battery.get("status", "BUENO")).pack(side="right")

        pct = battery.get("percent", 0)
        color = COLORS["accent_red"] if pct < 20 else (
            COLORS["accent_yellow"] if pct < 40 else COLORS["accent_green"])
        ctk.CTkLabel(main_card, text=f"Carga: {pct}%",
                    font=ctk.CTkFont(size=14), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=20)
        pb = ctk.CTkProgressBar(main_card, height=16, progress_color=color)
        pb.pack(fill="x", padx=20, pady=5)
        pb.set(pct / 100)

        stats_frame = ctk.CTkFrame(main_card, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=15)

        stats = [
            ("Estado", "Enchufada" if battery.get("plugged") else "En bateria"),
            ("Tiempo restante", battery.get("time_left", "N/A")),
            ("Salud", f"{battery.get('health_percent','N/A')}%" if battery.get('health_percent') else "N/A"),
            ("Capacidad diseno", str(battery.get("design_capacity", "N/A"))),
            ("Capacidad carga completa", str(battery.get("full_charge_capacity", "N/A"))),
        ]
        for label, value in stats:
            row = ctk.CTkFrame(stats_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
            row.pack(fill="x", pady=3)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=15, pady=8)
            ctk.CTkLabel(inner, text=label, font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_secondary"]).pack(side="left")
            ctk.CTkLabel(inner, text=value, font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(side="right")

        ctk.CTkLabel(main_card, text="").pack(pady=5)

        # Consejos
        tips_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        tips_card.pack(fill="x", pady=8)
        ctk.CTkLabel(tips_card, text="Consejos para prolongar la bateria",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))
        tips = [
            "Mantener la carga entre 20% y 80% para mayor vida util",
            "Evitar temperaturas extremas (el calor dana las baterias de litio)",
            "No dejar la laptop enchufada al 100% por largos periodos",
            "Reducir brillo de pantalla para aumentar autonomia",
            "Calibrar la bateria cada 2-3 meses",
        ]
        for tip in tips:
            ctk.CTkLabel(tips_card, text=f"• {tip}", font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", padx=25, pady=3)
        ctk.CTkLabel(tips_card, text="").pack(pady=5)

    # ── PÁGINA LIMPIEZA ──
    def show_cleanup(self):
        self._activate_nav("limpieza")
        self.page_title.configure(text="Limpieza de Archivos Temporales")
        self._clear_content()

        temp_data = self.all_data.get("temp_files", {})

        # Resumen
        summary_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                    corner_radius=12, border_width=1,
                                    border_color=COLORS["border"])
        summary_card.pack(fill="x", pady=8)

        header = ctk.CTkFrame(summary_card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Archivos Temporales Detectados",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=temp_data.get("status", "BUENO")).pack(side="right")

        total_gb = temp_data.get("total_gb", 0)
        total_mb = temp_data.get("total_mb", 0)

        ctk.CTkLabel(summary_card,
                    text=f"Total: {total_gb} GB ({total_mb} MB) recuperables",
                    font=ctk.CTkFont(size=22, weight="bold"),
                    text_color=COLORS["accent_yellow"]).pack(padx=20, pady=10)

        self.clean_btn = ctk.CTkButton(
            summary_card, text="Limpiar Archivos Temporales",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#2a8a3a",
            corner_radius=8, height=44,
            command=self._do_cleanup
        )
        self.clean_btn.pack(padx=20, pady=(5, 15))

        if temp_data.get("locations"):
            locations_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                         corner_radius=12, border_width=1,
                                         border_color=COLORS["border"])
            locations_card.pack(fill="x", pady=8)
            ctk.CTkLabel(locations_card, text="Ubicaciones con archivos temporales",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

            for loc in temp_data["locations"]:
                row = ctk.CTkFrame(locations_card, fg_color=COLORS["bg_card2"], corner_radius=8)
                row.pack(fill="x", padx=20, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=15, pady=10)
                ctk.CTkLabel(inner, text=loc["name"],
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["text_primary"]).pack(side="left")
                ctk.CTkLabel(inner, text=f"{loc['size_mb']} MB",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_yellow"]).pack(side="right")
                ctk.CTkLabel(locations_card, text=loc["path"],
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["text_secondary"]).pack(anchor="w", padx=35, pady=(0, 5))

            ctk.CTkLabel(locations_card, text="").pack(pady=5)

        self.clean_log = ctk.CTkTextbox(
            self.content_frame, fg_color=COLORS["bg_card"],
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(family="Consolas", size=11),
            height=150, corner_radius=12, border_width=1,
            border_color=COLORS["border"]
        )
        self.clean_log.pack(fill="x", pady=8)
        self.clean_log.insert("end", "Listo para limpiar. Presiona el boton de limpieza.\n")
        self.clean_log.configure(state="disabled")

    def _do_cleanup(self):
        self.clean_btn.configure(state="disabled", text="Limpiando...")
        self.clean_log.configure(state="normal")
        self.clean_log.delete("1.0", "end")
        self.clean_log.insert("end", "Iniciando limpieza de archivos temporales...\n")
        self.clean_log.configure(state="disabled")

        def cleanup_thread():
            result = self.engine.clean_temp_files()
            self.after(0, lambda: self._cleanup_done(result))

        threading.Thread(target=cleanup_thread, daemon=True).start()

    def _cleanup_done(self, result):
        self.clean_btn.configure(state="normal", text="Limpiar Archivos Temporales")
        cleaned = result.get("cleaned_mb", 0)
        errors = result.get("errors", 0)
        self.clean_log.configure(state="normal")
        self.clean_log.insert("end", f"Limpieza completada\n")
        self.clean_log.insert("end", f"   Espacio liberado: {cleaned} MB\n")
        self.clean_log.insert("end", f"   Archivos que no pudieron eliminarse: {errors}\n")
        self.clean_log.insert("end", f"   Nota: Algunos archivos en uso no pueden eliminarse\n")
        self.clean_log.configure(state="disabled")
        self.all_data["temp_files"] = self.engine.check_temp_files()

    # ── PÁGINA INICIO ──
    def show_startup(self):
        self._activate_nav("inicio")
        self.page_title.configure(text="Programas de Inicio")
        self._clear_content()

        startup = self.all_data.get("startup", {})
        items = startup.get("items", [])

        summary = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
        summary.pack(fill="x", pady=8)

        header = ctk.CTkFrame(summary, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Programas que inician con Windows",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=startup.get("status","BUENO")).pack(side="right")

        count = len(items)
        color = COLORS["accent_green"] if count <= 10 else (
            COLORS["accent_yellow"] if count <= 20 else COLORS["accent_red"])
        ctk.CTkLabel(summary, text=f"{count} programas detectados",
                    font=ctk.CTkFont(size=22, weight="bold"),
                    text_color=color).pack(padx=20, pady=10)
        ctk.CTkLabel(summary,
                    text="Muchos programas de inicio ralentizan el arranque de Windows",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(padx=20, pady=(0, 5))

        ctk.CTkButton(
            summary, text="Abrir Administrador de Tareas (Inicio)",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_card2"],
            hover_color=COLORS["border"],
            corner_radius=8, height=36,
            command=lambda: subprocess.Popen(["taskmgr"])
        ).pack(padx=20, pady=(5, 15))

        list_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        list_card.pack(fill="x", pady=8)
        ctk.CTkLabel(list_card, text="Lista de programas de inicio",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

        for i, item in enumerate(items):
            row = ctk.CTkFrame(list_card, fg_color=COLORS["bg_card2"] if i % 2 == 0 else COLORS["bg_card"],
                              corner_radius=6)
            row.pack(fill="x", padx=20, pady=1)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=15, pady=6)
            ctk.CTkLabel(inner, text=item.get("name","N/A"),
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(side="left")
            ctk.CTkLabel(inner, text=item.get("location",""),
                        font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(side="right")
            cmd = item.get("command","")
            if len(cmd) > 100:
                cmd = cmd[:100] + "..."
            ctk.CTkLabel(row, text=cmd, font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", padx=15, pady=(0, 5))

        ctk.CTkLabel(list_card, text="").pack(pady=5)

    # ── PÁGINA DRIVERS ──
    def show_drivers(self):
        self._activate_nav("drivers")
        self.page_title.configure(text="Estado de Drivers")
        self._clear_content()

        drivers = self.all_data.get("drivers", {})

        summary = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
        summary.pack(fill="x", pady=8)

        header = ctk.CTkFrame(summary, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Diagnostico de Drivers",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=drivers.get("status","INFO")).pack(side="right")

        ctk.CTkLabel(summary, text=drivers.get("message", "Verificando..."),
                    font=ctk.CTkFont(size=14), text_color=COLORS["text_secondary"]).pack(padx=20, pady=10)

        problem_count = drivers.get("problem_count", 0)
        ok_count = drivers.get("ok_count", 0)

        stats_frame = ctk.CTkFrame(summary, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=(0, 15))

        for label, value, color in [
            ("Dispositivos OK", ok_count, COLORS["accent_green"]),
            ("Con problemas", problem_count, COLORS["accent_red"]),
        ]:
            item = ctk.CTkFrame(stats_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
            item.pack(side="left", padx=8)
            ctk.CTkLabel(item, text=str(value),
                        font=ctk.CTkFont(size=24, weight="bold"),
                        text_color=color).pack(padx=15, pady=(8, 0))
            ctk.CTkLabel(item, text=label,
                        font=ctk.CTkFont(size=11),
                        text_color=COLORS["text_secondary"]).pack(padx=15, pady=(0, 8))

        ctk.CTkButton(
            summary, text="Abrir Administrador de Dispositivos",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_card2"],
            hover_color=COLORS["border"],
            corner_radius=8, height=36,
            command=lambda: subprocess.Popen(["devmgmt.msc"], shell=True)
        ).pack(padx=20, pady=(0, 15))

        problem_devices = drivers.get("problem_drivers", [])
        if problem_devices:
            problems_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                        corner_radius=12, border_width=1,
                                        border_color="#3d1a1a")
            problems_card.pack(fill="x", pady=8)
            ctk.CTkLabel(problems_card, text="Dispositivos con problemas",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["accent_red"]).pack(anchor="w", padx=20, pady=(15, 10))

            for device in problem_devices:
                row = ctk.CTkFrame(problems_card, fg_color="#3d1a1a", corner_radius=8)
                row.pack(fill="x", padx=20, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=15, pady=8)
                ctk.CTkLabel(inner, text=device.get("name","N/A"),
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_red"]).pack(side="left")
                ctk.CTkLabel(inner, text=f"Codigo de error: {device.get('error_code','N/A')}",
                            font=ctk.CTkFont(size=11),
                            text_color=COLORS["text_secondary"]).pack(side="right")

            ctk.CTkLabel(problems_card, text="").pack(pady=5)

    # ── PÁGINA SEGURIDAD ──
    def show_security(self):
        self._activate_nav("seguridad")
        self.page_title.configure(text="Seguridad y Amenazas")
        self._clear_content()

        security = self.all_data.get("security", {})
        checks = security.get("checks", [])

        # ── PANEL 1: Estado de defensas ──
        summary = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
        summary.pack(fill="x", pady=8)

        header = ctk.CTkFrame(summary, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Estado de Defensas del Sistema",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=security.get("status","INFO")).pack(side="right")

        critical_count = sum(1 for c in checks if c.get("status") in ["CRÍTICO","CRITICO"])
        warning_count = sum(1 for c in checks if c.get("status") == "ADVERTENCIA")
        good_count = sum(1 for c in checks if c.get("status") == "BUENO")

        stats_frame = ctk.CTkFrame(summary, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=10)
        for label, value, color in [
            ("Correcto", good_count, COLORS["accent_green"]),
            ("Advertencia", warning_count, COLORS["accent_yellow"]),
            ("Critico", critical_count, COLORS["accent_red"]),
        ]:
            item = ctk.CTkFrame(stats_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
            item.pack(side="left", padx=8)
            ctk.CTkLabel(item, text=str(value),
                        font=ctk.CTkFont(size=24, weight="bold"),
                        text_color=color).pack(padx=15, pady=(8, 0))
            ctk.CTkLabel(item, text=label,
                        font=ctk.CTkFont(size=11),
                        text_color=COLORS["text_secondary"]).pack(padx=15, pady=(0, 8))

        btn_row = ctk.CTkFrame(summary, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(5, 15))
        ctk.CTkButton(
            btn_row, text="Abrir Seguridad de Windows",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_card2"],
            hover_color=COLORS["border"],
            corner_radius=8, height=36,
            command=lambda: subprocess.Popen(["windowsdefender:"], shell=True)
        ).pack(side="left", padx=(0, 8))

        for check in checks:
            row = ctk.CTkFrame(summary, fg_color=COLORS["bg_card2"], corner_radius=8)
            row.pack(fill="x", padx=20, pady=2)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=15, pady=8)
            ctk.CTkLabel(inner, text=check.get("name","N/A"),
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_primary"]).pack(side="left")
            ctk.CTkLabel(inner, text=check.get("value","N/A"),
                        font=ctk.CTkFont(size=12),
                        text_color=COLORS["text_secondary"]).pack(side="right", padx=10)
            StatusBadge(inner, status=check.get("status","INFO")).pack(side="right")
        ctk.CTkLabel(summary, text="").pack(pady=3)

        # ── PANEL 2: Escaneo de Windows Defender ──
        scan_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        scan_card.pack(fill="x", pady=8)

        scan_header = ctk.CTkFrame(scan_card, fg_color="transparent")
        scan_header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(scan_header, text="Escaneo Rapido con Windows Defender",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkLabel(scan_card,
                    text="Dispara un escaneo rapido de Windows Defender para buscar malware activo.",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=20)

        scan_log = ctk.CTkTextbox(
            scan_card, fg_color=COLORS["bg_card2"],
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(family="Consolas", size=11),
            height=100, corner_radius=8
        )
        scan_log.pack(fill="x", padx=20, pady=8)
        scan_log.insert("end", "Listo. Presiona el boton para iniciar el escaneo de Defender.\n")
        scan_log.configure(state="disabled")

        self._scan_btn = ctk.CTkButton(
            scan_card,
            text="Iniciar Escaneo Rapido de Defender",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent_blue"],
            hover_color="#1a7fe0",
            corner_radius=8, height=40,
            command=lambda: self._run_defender_scan(scan_log)
        )
        self._scan_btn.pack(padx=20, pady=(0, 15))

        # ── PANEL 3: Historial de amenazas ──
        hist_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        hist_card.pack(fill="x", pady=8)

        hist_header = ctk.CTkFrame(hist_card, fg_color="transparent")
        hist_header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(hist_header, text="Historial de Amenazas (Defender)",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")

        self._hist_result_frame = ctk.CTkFrame(hist_card, fg_color="transparent")
        self._hist_result_frame.pack(fill="x", padx=20)

        ctk.CTkLabel(self._hist_result_frame,
                    text="Presiona el boton para ver el historial de amenazas detectadas por Defender.",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w")

        ctk.CTkButton(
            hist_card,
            text="Consultar Historial de Amenazas",
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["accent_purple"],
            hover_color="#9060cc",
            corner_radius=8, height=40,
            command=lambda: self._load_threat_history(self._hist_result_frame)
        ).pack(padx=20, pady=(8, 15))

        # ── PANEL 4: Análisis de procesos sospechosos ──
        proc_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        proc_card.pack(fill="x", pady=8)

        proc_header = ctk.CTkFrame(proc_card, fg_color="transparent")
        proc_header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(proc_header, text="Analisis de Procesos Sospechosos",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkLabel(proc_card,
                    text=(
                        "Compara todos los procesos activos contra una base de 150+ nombres de malware conocido.\n"
                        "Tambien detecta procesos con CPU excessivamente alto (posible minero de criptomonedas)."
                    ),
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"],
                    justify="left").pack(anchor="w", padx=20)

        self._proc_result_frame = ctk.CTkFrame(proc_card, fg_color="transparent")
        self._proc_result_frame.pack(fill="x", padx=20, pady=5)

        proc_btn_row = ctk.CTkFrame(proc_card, fg_color="transparent")
        proc_btn_row.pack(fill="x", padx=20, pady=(5, 15))

        self._proc_scan_btn = ctk.CTkButton(
            proc_btn_row,
            text="Escanear Procesos Activos",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent_orange"],
            hover_color="#c05030",
            corner_radius=8, height=40,
            command=lambda: self._run_process_scan(self._proc_result_frame)
        )
        self._proc_scan_btn.pack(side="left")

        # ── PANEL 5: Conexiones de red sospechosas ──
        net_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                corner_radius=12, border_width=1,
                                border_color=COLORS["border"])
        net_card.pack(fill="x", pady=8)

        net_header = ctk.CTkFrame(net_card, fg_color="transparent")
        net_header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(net_header, text="Conexiones de Red Sospechosas",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")

        ctk.CTkLabel(net_card,
                    text=(
                        "Revisa las conexiones de red activas buscando puertos tipicamente usados por RATs,\n"
                        "botnets, Tor, Metasploit y otros malware de acceso remoto."
                    ),
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"],
                    justify="left").pack(anchor="w", padx=20)

        self._net_result_frame = ctk.CTkFrame(net_card, fg_color="transparent")
        self._net_result_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkButton(
            net_card,
            text="Analizar Conexiones de Red",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#2a8a3a",
            corner_radius=8, height=40,
            command=lambda: self._run_net_scan(self._net_result_frame)
        ).pack(padx=20, pady=(5, 15))

        # ── PANEL 6: Startup malware check ──
        startup_sec_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                        corner_radius=12, border_width=1,
                                        border_color=COLORS["border"])
        startup_sec_card.pack(fill="x", pady=8)

        ctk.CTkLabel(startup_sec_card, text="Malware en Programas de Inicio",
                    font=ctk.CTkFont(size=14, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(startup_sec_card,
                    text="Verifica si algun programa de inicio coincide con malware conocido o se ejecuta desde carpetas TEMP.",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(anchor="w", padx=20)

        self._startup_sec_frame = ctk.CTkFrame(startup_sec_card, fg_color="transparent")
        self._startup_sec_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkButton(
            startup_sec_card,
            text="Verificar Inicio vs. Malware",
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["accent_yellow"],
            hover_color="#b08020",
            corner_radius=8, height=40,
            command=lambda: self._run_startup_sec_scan(self._startup_sec_frame)
        ).pack(padx=20, pady=(5, 15))

    # ── ACCIONES DE SEGURIDAD ──

    def _run_defender_scan(self, log_widget):
        """Lanza escaneo de Defender en hilo separado"""
        self._scan_btn.configure(state="disabled", text="Escaneando... (puede tardar minutos)")
        log_widget.configure(state="normal")
        log_widget.delete("1.0", "end")
        log_widget.insert("end", "Enviando solicitud a Windows Defender...\n")
        log_widget.configure(state="disabled")

        def _write(msg):
            self.after(0, lambda m=msg: self._append_log(log_widget, m))

        def _thread():
            result = self.engine.trigger_defender_quick_scan(log_callback=_write)
            def _done():
                self._scan_btn.configure(state="normal", text="Iniciar Escaneo Rapido de Defender")
                if result["success"]:
                    self._append_log(log_widget, "Escaneo finalizado. Revisa el Historial de Amenazas para ver resultados.")
                else:
                    self._append_log(log_widget, f"Resultado: {result['message']}")
            self.after(0, _done)

        threading.Thread(target=_thread, daemon=True).start()

    def _append_log(self, widget, msg):
        widget.configure(state="normal")
        widget.insert("end", f"  {msg}\n")
        widget.see("end")
        widget.configure(state="disabled")

    def _load_threat_history(self, frame):
        """Carga historial de amenazas de Defender"""
        for w in frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(frame, text="Consultando historial...",
                    font=ctk.CTkFont(size=12), text_color=COLORS["accent_blue"]).pack(anchor="w", pady=5)
        frame.update()

        def _thread():
            threats = self.engine.get_defender_threat_history()
            self.after(0, lambda: self._show_threat_history(frame, threats))

        threading.Thread(target=_thread, daemon=True).start()

    def _show_threat_history(self, frame, threats):
        for w in frame.winfo_children():
            w.destroy()
        detected = threats.get("detected", [])
        status = threats.get("status", "INFO")
        msg = threats.get("message", "")

        result_row = ctk.CTkFrame(frame, fg_color="transparent")
        result_row.pack(fill="x", pady=5)
        StatusBadge(result_row, status=status).pack(side="left")
        ctk.CTkLabel(result_row, text=f"  {msg}", font=ctk.CTkFont(size=12),
                    text_color=COLORS["text_secondary"]).pack(side="left", padx=8)

        if detected:
            for threat in detected[:10]:
                t_frame = ctk.CTkFrame(frame,
                                       fg_color="#3d1a1a" if not threat["remediated"] else COLORS["bg_card2"],
                                       corner_radius=8)
                t_frame.pack(fill="x", pady=2)
                inner = ctk.CTkFrame(t_frame, fg_color="transparent")
                inner.pack(fill="x", padx=12, pady=8)
                ctk.CTkLabel(inner, text=threat["process"] or "Desconocido",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_red"] if not threat["remediated"] else COLORS["text_primary"]).pack(side="left")
                rem_txt = "Remediado" if threat["remediated"] else "NO REMEDIADO"
                rem_color = COLORS["accent_green"] if threat["remediated"] else COLORS["accent_red"]
                ctk.CTkLabel(inner, text=rem_txt,
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color=rem_color).pack(side="right")
                ctk.CTkLabel(t_frame, text=f"Detectado: {threat['time'][:19]}",
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["text_secondary"]).pack(anchor="w", padx=12, pady=(0,5))

    def _run_process_scan(self, frame):
        """Escanea procesos sospechosos"""
        self._proc_scan_btn.configure(state="disabled", text="Escaneando procesos...")
        for w in frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(frame, text="Analizando procesos activos...",
                    font=ctk.CTkFont(size=12), text_color=COLORS["accent_blue"]).pack(anchor="w", pady=5)
        frame.update()

        def _thread():
            result = self.engine.scan_suspicious_processes()
            self.after(0, lambda: self._show_process_results(frame, result))

        threading.Thread(target=_thread, daemon=True).start()

    def _show_process_results(self, frame, result):
        self._proc_scan_btn.configure(state="normal", text="Escanear Procesos Activos")
        for w in frame.winfo_children():
            w.destroy()

        suspicious = result.get("suspicious", [])
        high_cpu = result.get("high_cpu", [])
        total = result.get("total", 0)
        status = result.get("status", "BUENO")

        summary_row = ctk.CTkFrame(frame, fg_color="transparent")
        summary_row.pack(fill="x", pady=5)
        StatusBadge(summary_row, status=status).pack(side="left")
        ctk.CTkLabel(summary_row,
                    text=f"  {total} procesos analizados — {len(suspicious)} sospechosos — {len(high_cpu)} con CPU alto",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(side="left", padx=8)

        if not suspicious and not high_cpu:
            ctk.CTkLabel(frame, text="No se detectaron procesos sospechosos.",
                        font=ctk.CTkFont(size=12), text_color=COLORS["accent_green"]).pack(anchor="w", pady=5)
        else:
            if suspicious:
                ctk.CTkLabel(frame, text="PROCESOS SOSPECHOSOS:",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_red"]).pack(anchor="w", pady=(8,3))
                for proc in suspicious[:15]:
                    p_frame = ctk.CTkFrame(frame, fg_color="#3d1a1a", corner_radius=8)
                    p_frame.pack(fill="x", pady=2)
                    inner = ctk.CTkFrame(p_frame, fg_color="transparent")
                    inner.pack(fill="x", padx=12, pady=5)
                    ctk.CTkLabel(inner,
                                text=f"{proc['name']} (PID {proc['pid']})",
                                font=ctk.CTkFont(size=12, weight="bold"),
                                text_color=COLORS["accent_red"]).pack(side="left")
                    ctk.CTkLabel(inner,
                                text=f"CPU: {proc['cpu']}% | RAM: {proc['mem']}%",
                                font=ctk.CTkFont(size=11),
                                text_color=COLORS["text_secondary"]).pack(side="right")
                    ctk.CTkLabel(p_frame,
                                text=f"Razon: {proc['suspicious_reason']}",
                                font=ctk.CTkFont(size=10),
                                text_color=COLORS["accent_yellow"]).pack(anchor="w", padx=12, pady=(0,3))
                    # Botón buscar en VirusTotal
                    ctk.CTkButton(
                        p_frame,
                        text=f"Buscar '{proc['name']}' en VirusTotal / Web",
                        font=ctk.CTkFont(size=10),
                        fg_color=COLORS["bg_card"],
                        hover_color=COLORS["border"],
                        height=26, corner_radius=6,
                        command=lambda n=proc["name"]: self.engine.search_malware_online(n)
                    ).pack(anchor="w", padx=12, pady=(0, 6))

            if high_cpu:
                ctk.CTkLabel(frame, text="PROCESOS CON CPU SOSPECHOSAMENTE ALTO:",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_yellow"]).pack(anchor="w", pady=(8, 3))
                for proc in high_cpu[:5]:
                    p_frame = ctk.CTkFrame(frame, fg_color="#3d2e0a", corner_radius=8)
                    p_frame.pack(fill="x", pady=2)
                    inner = ctk.CTkFrame(p_frame, fg_color="transparent")
                    inner.pack(fill="x", padx=12, pady=6)
                    ctk.CTkLabel(inner,
                                text=f"{proc['name']} (PID {proc['pid']})",
                                font=ctk.CTkFont(size=12, weight="bold"),
                                text_color=COLORS["accent_yellow"]).pack(side="left")
                    ctk.CTkLabel(inner,
                                text=f"CPU: {proc['cpu']}% | RAM: {proc['mem']}%",
                                font=ctk.CTkFont(size=11, weight="bold"),
                                text_color=COLORS["accent_orange"]).pack(side="right")

    def _run_net_scan(self, frame):
        """Escanea conexiones de red sospechosas"""
        for w in frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(frame, text="Analizando conexiones de red...",
                    font=ctk.CTkFont(size=12), text_color=COLORS["accent_blue"]).pack(anchor="w", pady=5)
        frame.update()

        def _thread():
            result = self.engine.check_suspicious_network_connections()
            self.after(0, lambda: self._show_net_results(frame, result))

        threading.Thread(target=_thread, daemon=True).start()

    def _show_net_results(self, frame, result):
        for w in frame.winfo_children():
            w.destroy()
        suspicious = result.get("suspicious", [])
        connections = result.get("connections", [])
        status = result.get("status", "BUENO")

        summary_row = ctk.CTkFrame(frame, fg_color="transparent")
        summary_row.pack(fill="x", pady=5)
        StatusBadge(summary_row, status=status).pack(side="left")
        ctk.CTkLabel(summary_row,
                    text=f"  {result.get('total',0)} conexiones activas — {len(suspicious)} sospechosas",
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(side="left", padx=8)

        if not suspicious:
            ctk.CTkLabel(frame, text="No se detectaron conexiones en puertos sospechosos.",
                        font=ctk.CTkFont(size=12), text_color=COLORS["accent_green"]).pack(anchor="w", pady=5)
        else:
            ctk.CTkLabel(frame, text="CONEXIONES EN PUERTOS SOSPECHOSOS:",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS["accent_red"]).pack(anchor="w", pady=(8, 3))
            for conn in suspicious:
                c_frame = ctk.CTkFrame(frame, fg_color="#3d1a1a", corner_radius=8)
                c_frame.pack(fill="x", pady=2)
                inner = ctk.CTkFrame(c_frame, fg_color="transparent")
                inner.pack(fill="x", padx=12, pady=6)
                ctk.CTkLabel(inner,
                            text=f"{conn['process']} (PID {conn['pid']})",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_red"]).pack(side="left")
                ctk.CTkLabel(inner,
                            text=f"{conn['remote_ip']}:{conn['remote_port']}",
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color=COLORS["accent_orange"]).pack(side="right")
                ctk.CTkLabel(c_frame,
                            text=f"Razon: {conn['suspicious_reason']}",
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["accent_yellow"]).pack(anchor="w", padx=12, pady=(0, 4))

        # Conexiones externas normales (informativo)
        if connections:
            ctk.CTkLabel(frame, text=f"Otras conexiones externas ({len(connections)}):",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=COLORS["text_secondary"]).pack(anchor="w", pady=(8,3))
            for conn in connections[:10]:
                c_row = ctk.CTkFrame(frame, fg_color=COLORS["bg_card2"], corner_radius=6)
                c_row.pack(fill="x", pady=1)
                inner = ctk.CTkFrame(c_row, fg_color="transparent")
                inner.pack(fill="x", padx=12, pady=5)
                ctk.CTkLabel(inner, text=conn["process"],
                            font=ctk.CTkFont(size=11),
                            text_color=COLORS["text_primary"]).pack(side="left")
                ctk.CTkLabel(inner,
                            text=f"{conn['remote_ip']}:{conn['remote_port']}",
                            font=ctk.CTkFont(size=11),
                            text_color=COLORS["text_secondary"]).pack(side="right")

    def _run_startup_sec_scan(self, frame):
        """Verifica inicio contra malware. Usa los datos del escaneo previo si existen,
        o los re-obtiene si no hay datos de startup guardados."""
        for w in frame.winfo_children():
            w.destroy()
        loading_lbl = ctk.CTkLabel(frame, text="Verificando programas de inicio contra base de malware...",
                    font=ctk.CTkFont(size=12), text_color=COLORS["accent_blue"])
        loading_lbl.pack(anchor="w", pady=5)
        frame.update()

        def _thread():
            # Reusar los items del escaneo principal si están disponibles
            startup_data = self.all_data.get("startup", {})
            startup_items = startup_data.get("items") if isinstance(startup_data, dict) else None
            # Si no hay items guardados, obtenerlos ahora
            if not startup_items:
                startup_items = self.engine.check_startup_programs().get("items", [])
            result = self.engine.check_suspicious_startup_malware(startup_items=startup_items)
            self.after(0, lambda: self._show_startup_sec_results(frame, result))

        threading.Thread(target=_thread, daemon=True).start()

    def _show_startup_sec_results(self, frame, result):
        for w in frame.winfo_children():
            w.destroy()
        suspicious = result.get("suspicious", [])
        total_checked = result.get("total_checked", 0)
        status = result.get("status", "BUENO")

        summary_row = ctk.CTkFrame(frame, fg_color="transparent")
        summary_row.pack(fill="x", pady=5)
        StatusBadge(summary_row, status=status).pack(side="left")
        if suspicious:
            msg = f"  {len(suspicious)} entrada(s) sospechosa(s) de {total_checked} analizadas"
        else:
            msg = f"  No se encontro malware en {total_checked} programas de inicio analizados"
        ctk.CTkLabel(summary_row, text=msg, font=ctk.CTkFont(size=12),
                    text_color=COLORS["text_secondary"]).pack(side="left", padx=8)

        if suspicious:
            ctk.CTkLabel(frame, text="ENTRADAS SOSPECHOSAS EN EL INICIO:",
                        font=ctk.CTkFont(size=11, weight="bold"),
                        text_color=COLORS["accent_red"]).pack(anchor="w", pady=(6, 2))
            for item in suspicious:
                s_frame = ctk.CTkFrame(frame, fg_color="#3d1a1a", corner_radius=8)
                s_frame.pack(fill="x", pady=2)
                inner = ctk.CTkFrame(s_frame, fg_color="transparent")
                inner.pack(fill="x", padx=12, pady=6)
                ctk.CTkLabel(inner, text=item.get("name", "N/A"),
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_red"]).pack(side="left")
                loc = item.get("location", "")
                if loc:
                    ctk.CTkLabel(inner, text=loc,
                                font=ctk.CTkFont(size=10),
                                text_color=COLORS["text_secondary"]).pack(side="right")
                ctk.CTkLabel(s_frame, text=f"Razon: {item.get('reason', 'N/A')}",
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["accent_yellow"]).pack(anchor="w", padx=12)
                cmd = (item.get("command") or "")[:100]
                if cmd:
                    ctk.CTkLabel(s_frame, text=cmd,
                                font=ctk.CTkFont(size=10, family="Consolas"),
                                text_color=COLORS["text_secondary"]).pack(anchor="w", padx=12, pady=(0,5))
                # Botón buscar en web
                ctk.CTkButton(
                    s_frame,
                    text=f"Buscar '{item.get('name','?')}' en VirusTotal / Web",
                    font=ctk.CTkFont(size=10),
                    fg_color=COLORS["bg_card"],
                    hover_color=COLORS["border"],
                    height=26, corner_radius=6,
                    command=lambda n=item.get("name", ""): self.engine.search_malware_online(n)
                ).pack(anchor="w", padx=12, pady=(0, 8))
        else:
            ctk.CTkLabel(frame, text="Todos los programas de inicio parecen legitimos.",
                        font=ctk.CTkFont(size=12), text_color=COLORS["accent_green"]).pack(anchor="w", pady=5)



    # ── PÁGINA RED ──
    def show_network(self):
        self._activate_nav("red")
        self.page_title.configure(text="Conectividad de Red")
        self._clear_content()

        net = self.all_data.get("network", {})

        ping_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                 corner_radius=12, border_width=1,
                                 border_color=COLORS["border"])
        ping_card.pack(fill="x", pady=8)

        header = ctk.CTkFrame(ping_card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Conectividad de Red",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=net.get("status","INFO")).pack(side="right")

        net_stats = [
            ("IP Local", net.get("ip_local","N/A")),
            ("Hostname", net.get("hostname","N/A")),
            ("MB enviados", str(net.get("bytes_sent_mb","N/A"))),
            ("MB recibidos", str(net.get("bytes_recv_mb","N/A"))),
        ]
        stats_frame = ctk.CTkFrame(ping_card, fg_color="transparent")
        stats_frame.pack(fill="x", padx=20, pady=10)
        for label, value in net_stats:
            item = ctk.CTkFrame(stats_frame, fg_color=COLORS["bg_card2"], corner_radius=8)
            item.pack(side="left", padx=5)
            ctk.CTkLabel(item, text=value, font=ctk.CTkFont(size=12, weight="bold"),
                        text_color=COLORS["accent_blue"]).pack(padx=12, pady=(8, 0))
            ctk.CTkLabel(item, text=label, font=ctk.CTkFont(size=10),
                        text_color=COLORS["text_secondary"]).pack(padx=12, pady=(0, 8))

        pings = net.get("ping_results", [])
        if pings:
            ctk.CTkLabel(ping_card, text="Pruebas de conectividad",
                        font=ctk.CTkFont(size=13, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(10, 5))
            for ping in pings:
                row = ctk.CTkFrame(ping_card, fg_color=COLORS["bg_card2"], corner_radius=8)
                row.pack(fill="x", padx=20, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=15, pady=10)
                ctk.CTkLabel(inner, text=f"{ping['target']} ({ping['ip']})",
                            font=ctk.CTkFont(size=12)).pack(side="left")
                ctk.CTkLabel(inner, text=f"{ping['avg_ms']} ms",
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["accent_blue"]).pack(side="right", padx=10)
                StatusBadge(inner, status=ping.get("status","INFO")).pack(side="right")

        ctk.CTkLabel(ping_card, text="").pack(pady=5)

        interfaces = net.get("interfaces", [])
        if interfaces:
            iface_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                      corner_radius=12, border_width=1,
                                      border_color=COLORS["border"])
            iface_card.pack(fill="x", pady=8)
            ctk.CTkLabel(iface_card, text="Interfaces de red",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

            for iface in interfaces:
                row = ctk.CTkFrame(iface_card, fg_color=COLORS["bg_card2"], corner_radius=8)
                row.pack(fill="x", padx=20, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=15, pady=8)
                status = "BUENO" if iface.get("is_up") else "ADVERTENCIA"
                ctk.CTkLabel(inner, text=iface.get("name","N/A"),
                            font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=COLORS["text_primary"]).pack(side="left")
                StatusBadge(inner, status=status).pack(side="right")
                addresses = ", ".join(iface.get("addresses", []))
                speed = iface.get("speed_mbps", 0)
                ctk.CTkLabel(row, text=f"IP: {addresses or 'N/A'} | Velocidad: {speed} Mbps",
                            font=ctk.CTkFont(size=10),
                            text_color=COLORS["text_secondary"]).pack(anchor="w", padx=15, pady=(0,5))

            ctk.CTkLabel(iface_card, text="").pack(pady=5)

    # ── PÁGINA ACTUALIZACIONES ──
    def show_updates(self):
        self._activate_nav("actualizaciones")
        self.page_title.configure(text="Actualizaciones de Windows")
        self._clear_content()

        updates = self.all_data.get("updates", {})

        summary = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                               corner_radius=12, border_width=1,
                               border_color=COLORS["border"])
        summary.pack(fill="x", pady=8)

        header = ctk.CTkFrame(summary, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 5))
        ctk.CTkLabel(header, text="Estado de Actualizaciones",
                    font=ctk.CTkFont(size=15, weight="bold"),
                    text_color=COLORS["text_primary"]).pack(side="left")
        StatusBadge(header, status=updates.get("status","INFO")).pack(side="right")

        count = updates.get("count", -1)
        if count >= 0:
            color = COLORS["accent_green"] if count == 0 else COLORS["accent_yellow"]
            ctk.CTkLabel(summary, text=f"{count} actualizacion(es) pendiente(s)",
                        font=ctk.CTkFont(size=22, weight="bold"),
                        text_color=color).pack(padx=20, pady=10)

        ctk.CTkLabel(summary, text=updates.get("message",""),
                    font=ctk.CTkFont(size=12), text_color=COLORS["text_secondary"]).pack(padx=20)

        ctk.CTkButton(
            summary, text="Abrir Windows Update",
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_card2"],
            hover_color=COLORS["border"],
            corner_radius=8, height=36,
            command=lambda: subprocess.Popen(["ms-settings:windowsupdate"], shell=True)
        ).pack(padx=20, pady=15)

        available = updates.get("available", [])
        if available:
            list_card = ctk.CTkFrame(self.content_frame, fg_color=COLORS["bg_card"],
                                     corner_radius=12, border_width=1,
                                     border_color=COLORS["border"])
            list_card.pack(fill="x", pady=8)
            ctk.CTkLabel(list_card, text="Actualizaciones disponibles",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15, 10))

            for i, update_name in enumerate(available):
                row = ctk.CTkFrame(list_card,
                                  fg_color=COLORS["bg_card2"] if i % 2 == 0 else COLORS["bg_card"],
                                  corner_radius=6)
                row.pack(fill="x", padx=20, pady=1)
                ctk.CTkLabel(row, text=f"  {update_name}",
                            font=ctk.CTkFont(size=12),
                            text_color=COLORS["text_primary"]).pack(anchor="w", padx=15, pady=8)

            ctk.CTkLabel(list_card, text="").pack(pady=5)

    # ── EXPORTAR REPORTE ──
    def export_report(self):
        if not self.scan_complete:
            messagebox.showwarning("Atencion", "Espera a que termine el escaneo antes de exportar.")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML Report", "*.html"), ("All Files", "*.*")],
            initialfile=f"PC_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
            title="Guardar reporte"
        )
        if filepath:
            try:
                result_path = self.engine.generate_html_report(self.all_data, filepath)
                if messagebox.askyesno("Reporte generado",
                                       f"Reporte guardado en:\n{result_path}\n\nDeseas abrirlo ahora?"):
                    os.startfile(result_path)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo generar el reporte:\n{str(e)}")


# ─────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = PCExaminerApp()
    app.mainloop()
