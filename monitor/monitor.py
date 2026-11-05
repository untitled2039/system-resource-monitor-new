import time
from .i18n import tr
from tkinter import messagebox
import psutil
from plyer import notification
import threading
import subprocess
import platform
import os
import sys

# Multiple GPU monitoring approaches
try:
    import GPUtil
    GPUTIL_AVAILABLE = True
except ImportError:
    GPUTIL_AVAILABLE = False

try:
    import nvidia_ml_py3 as nvml
    nvml.nvmlInit()
    NVML_AVAILABLE = True
except (ImportError, Exception):
    NVML_AVAILABLE = False

class _PdhGpuCounter:
    """GPU load from the Windows "GPU Engine" performance counters, read in-process (PDH).

    Replaces starting PowerShell every second, which cost a whole new process each sample.
    Same rule as Task Manager: sum the instances of each engine type, take the busiest type.
    """
    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_NOCAP100 = 0x00008000
    PDH_MORE_DATA = 0x800007D2

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class _Value(ctypes.Union):
            _fields_ = [("longValue", ctypes.c_long), ("doubleValue", ctypes.c_double),
                        ("largeValue", ctypes.c_longlong), ("AnsiStringValue", ctypes.c_char_p),
                        ("WideStringValue", ctypes.c_wchar_p)]

        class _FmtValue(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("CStatus", wintypes.DWORD), ("u", _Value)]

        class _Item(ctypes.Structure):
            _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _FmtValue)]

        self.ctypes, self.wintypes, self.Item = ctypes, wintypes, _Item
        pdh = ctypes.WinDLL("pdh")
        pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_void_p)]
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                     ctypes.POINTER(wintypes.DWORD),
                                                     ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        for function in (pdh.PdhOpenQueryW, pdh.PdhAddEnglishCounterW, pdh.PdhCollectQueryData,
                         pdh.PdhGetFormattedCounterArrayW, pdh.PdhCloseQuery):
            function.restype = ctypes.c_long
        self.pdh = pdh
        self.query = None
        self.opened_at = 0.0
        self._open()

    def _open(self):
        ctypes = self.ctypes
        self.close()
        query, counter = ctypes.c_void_p(), ctypes.c_void_p()
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(query)) != 0:
            raise OSError("PdhOpenQuery failed")
        if self.pdh.PdhAddEnglishCounterW(query, r"\GPU Engine(*)\Utilization Percentage", None,
                                          ctypes.byref(counter)) != 0:
            self.pdh.PdhCloseQuery(query)
            raise OSError("GPU Engine counters are not available")
        self.query, self.counter = query, counter
        self.pdh.PdhCollectQueryData(query)  # first sample; rates need two
        self.opened_at = time.time()

    def read(self):
        ctypes, wintypes = self.ctypes, self.wintypes
        if time.time() - self.opened_at > 60:
            self._open()  # picks up GPU engine instances of newly started processes
            return None
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return None
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = self.PDH_FMT_DOUBLE | self.PDH_FMT_NOCAP100
        status = self.pdh.PdhGetFormattedCounterArrayW(self.counter, fmt, ctypes.byref(size),
                                                       ctypes.byref(count), None) & 0xFFFFFFFF
        if status != self.PDH_MORE_DATA or not size.value:
            return 0.0 if status == 0 else None
        buffer = (ctypes.c_byte * size.value)()
        if self.pdh.PdhGetFormattedCounterArrayW(self.counter, fmt, ctypes.byref(size),
                                                 ctypes.byref(count), buffer) != 0:
            return None
        items = ctypes.cast(buffer, ctypes.POINTER(self.Item * count.value)).contents
        per_engine = {}
        for item in items:
            if item.FmtValue.CStatus not in (0, 1):  # PDH_CSTATUS_VALID_DATA / NEW_DATA
                continue
            name = item.szName or ""
            engine = name.rsplit("engtype_", 1)[-1] if "engtype_" in name else "other"
            per_engine[engine] = per_engine.get(engine, 0.0) + item.FmtValue.doubleValue
        return min(100.0, max(per_engine.values(), default=0.0))

    def close(self):
        if self.query:
            try:
                self.pdh.PdhCloseQuery(self.query)
            except Exception:
                pass
            self.query = None


_pdh_gpu = None
_pdh_failed = False
_last_gpu_value = 0.0


def get_amd_gpu_info():
    """GPU load for non-NVIDIA (AMD/Intel) GPUs via Windows performance counters."""
    global _pdh_gpu, _pdh_failed, _last_gpu_value
    if platform.system() != 'Windows' or _pdh_failed:
        return 0.0, 0.0
    try:
        if _pdh_gpu is None:
            _pdh_gpu = _PdhGpuCounter()
        value = _pdh_gpu.read()
        if value is not None:
            _last_gpu_value = value
    except Exception:
        _pdh_failed = True  # counters unavailable on this PC: report 0 instead of retrying
        _pdh_gpu = None
    return _last_gpu_value, 0.0

def get_gpu_info():
    """Get GPU usage information with AMD support"""
    gpu_usage = 0.0
    gpu_memory = 0.0

    if NVML_AVAILABLE:
        try:
            device_count = nvml.nvmlDeviceGetCount()
            if device_count > 0:
                handle = nvml.nvmlDeviceGetHandleByIndex(0)
                util = nvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_usage = util.gpu
                mem_info = nvml.nvmlDeviceGetMemoryInfo(handle)
                gpu_memory = (mem_info.used / mem_info.total) * 100
                return gpu_usage, gpu_memory
        except Exception:
            pass

    if GPUTIL_AVAILABLE:
        try:
            gpus = GPUtil.getGPUs()
            if gpus and len(gpus) > 0:
                gpu = gpus[0]
                gpu_usage = gpu.load * 100
                gpu_memory = gpu.memoryUtil * 100
                return gpu_usage, gpu_memory
        except Exception:
            pass

    gpu_usage, gpu_memory = get_amd_gpu_info()
    return gpu_usage, gpu_memory

def check_gpu_existence():
    """Check if GPU hardware exists"""

    if platform.system() == 'Windows':
        try:
            # FIXED: Add creationflags to prevent console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run([
                'wmic', 'path', 'win32_VideoController', 'get', 'name'
            ], capture_output=True, text=True, timeout=5, shell=True,
               startupinfo=startupinfo,
               creationflags=subprocess.CREATE_NO_WINDOW)

            if result.returncode == 0:
                output = result.stdout.lower()
                gpu_keywords = [
                    'nvidia', 'geforce', 'quadro', 'rtx', 'gtx',
                    'amd', 'radeon', 'rx', 'vega', 'navi',
                    'intel arc', 'intel iris', 'intel xe'
                ]
                if any(keyword in output for keyword in gpu_keywords):
                    return True
        except:
            pass

    elif platform.system() == 'Linux':
        try:
            if os.path.exists('/sys/class/drm/card0/device/vendor'):
                with open('/sys/class/drm/card0/device/vendor', 'r') as f:
                    vendor = f.read().strip()
                    if vendor in ['0x1002', '0x10de', '0x8086']:
                        return True
        except:
            pass

    return False

def get_gpu_diagnostic_info():
    """Get diagnostic information about GPU detection"""
    info = {
        'gpu_detected': check_gpu_existence(),
        'nvml_available': NVML_AVAILABLE,
        'gputil_available': GPUTIL_AVAILABLE,
        'platform': platform.system(),
        'gpu_type': 'Unknown'
    }

    if platform.system() == 'Windows':
        try:
            # FIXED: Add creationflags to prevent console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            result = subprocess.run([
                'wmic', 'path', 'win32_VideoController', 'get', 'name'
            ], capture_output=True, text=True, timeout=5, shell=True,
               startupinfo=startupinfo,
               creationflags=subprocess.CREATE_NO_WINDOW)

            if result.returncode == 0 and result.stdout:
                output = result.stdout.lower()
                if 'amd' in output or 'radeon' in output:
                    info['gpu_type'] = 'AMD'
                elif 'nvidia' in output or 'geforce' in output:
                    info['gpu_type'] = 'NVIDIA'
                elif 'intel' in output:
                    info['gpu_type'] = 'Intel'
        except:
            pass

    return info

def monitor_resources(self):
    cpu_high_start_time = None
    memory_high_start_time = None
    gpu_high_start_time = None

    try:
        gpu_info = get_gpu_diagnostic_info()
        self.gpu_info = gpu_info
    except:
        self.gpu_info = {'gpu_detected': False, 'gpu_type': 'Unknown'}

    while self.monitoring:
        try:
            if getattr(self, "remote_client", None):
                try:
                    sample = self.remote_client.sample(timeout=max(8, self.CPU_MON_INTERVAL + 3))
                    avg_cpu_percent = float(sample["cpu"])
                    memory_percent = float(sample["memory"])
                    gpu_percent = float(sample["gpu"] or 0)
                    gpu_memory_percent = float(sample["gpu_memory"] or 0)
                except Exception:
                    self.remote_client.close()
                    self.remote_client = None
                    self.remote_device_name = None
                    self.root.after(0, lambda: (
                        self.remote_status_label.configure(text=tr("Disconnected; monitoring local device")),
                        self.remote_disconnect_button.configure(state="disabled"),
                        self.process_title_label.configure(text=tr("Top 20 Processes by CPU Usage")),
                    ))
                    avg_cpu_percent = psutil.cpu_percent(interval=self.CPU_MON_INTERVAL)
                    memory_percent = psutil.virtual_memory().percent
                    gpu_percent, gpu_memory_percent = get_gpu_info()
            else:
                cpu_percent_per_core = psutil.cpu_percent(interval=self.CPU_MON_INTERVAL, percpu=True)
                avg_cpu_percent = sum(cpu_percent_per_core) / len(cpu_percent_per_core)
                memory_percent = psutil.virtual_memory().percent
                gpu_percent, gpu_memory_percent = get_gpu_info()

            self.cpu_history.append(avg_cpu_percent)
            self.memory_history.append(memory_percent)
            self.gpu_history.append(gpu_percent)
            self.gpu_memory_history.append(gpu_memory_percent)
            self.time_history.append(time.strftime('%H:%M:%S'))

            self.all_cpu_history.append(avg_cpu_percent)
            self.all_memory_history.append(memory_percent)
            self.all_gpu_history.append(gpu_percent)
            self.all_gpu_memory_history.append(gpu_memory_percent)
            self.all_time_history.append(time.strftime('%H:%M:%S'))

            self.root.after(0, lambda cpu=avg_cpu_percent, mem=memory_percent,
                            gpu=gpu_percent, gpu_mem=gpu_memory_percent:
                            self.update_metric_values(cpu, mem, gpu, gpu_mem))

            if getattr(self, "remote_client", None):
                self._publish_processes(sample.get("processes", []))
                scope_titles = {
                    "agent_app_only": "Top Processes (Android app only)",
                    "recent_apps": "Recently Used Apps (Android)",
                    "shizuku": "Top 20 Processes (Android, via Shizuku)",
                }
                scope = sample.get("process_scope")
                name = self.remote_device_name or "Remote device"
                if scope in scope_titles:
                    note = sample.get("agent_note") if scope != "shizuku" else None
                    suffix = f"  [{note}]" if note else ""
                    self.root.after(0, lambda device=name, title=tr(scope_titles[scope]), suffix=suffix:
                                    self.process_title_label.configure(text=f"{title} — {device}{suffix}"))
                cpu_note = tr({"frequency_estimate": " (CPU: clock-speed estimate)",
                               "unavailable": " (CPU unavailable)"}.get(sample.get("cpu_source"), ""))
                self.root.after(0, lambda device=name, note=cpu_note:
                                self.remote_status_label.configure(
                                    text=tr("Connected: {name}").format(name=device) + note))

            history = getattr(self, "history", None)
            if history is not None:
                try:
                    history.add((self.remote_device_name or "Remote device") if getattr(self, "remote_client", None)
                                else "__local__",
                                avg_cpu_percent, memory_percent, gpu_percent, gpu_memory_percent)
                    history.prune(self.alert_settings.get("history_days", 30))
                except Exception:
                    pass

            local = not getattr(self, "remote_client", None)
            self.alert_tracker.check(
                self.alert_settings,
                {"cpu": avg_cpu_percent, "memory": memory_percent,
                 "gpu": gpu_percent, "gpu_memory": gpu_memory_percent},
                self.remote_device_name or tr("this PC"),
                on_sent=lambda title, message, error, key, local=local: self.root.after(
                    0, lambda: self._on_alert_sent(title, message, error, key, local)),
                # RAM over the limit on this PC: the alert also starts a RAM cleanup.
                notes={"memory": tr(" Cleaning up RAM now.")} if local else None)

        except Exception:
            pass
