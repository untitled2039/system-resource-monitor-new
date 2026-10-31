"""Mem Reduct-style RAM cleanup for Windows.

Mem Reduct does not close anything. It asks the kernel to empty its memory lists:

1. Working sets      - every process gives back pages it is not actively using
2. System file cache - the kernel's file cache working set is emptied
3. Modified list     - dirty pages are written to the page file, so they become standby
4. Standby list      - cached-but-unused pages are discarded (low priority first, then all)
5. Combine pages     - identical memory pages are merged (Windows 10+)

Steps 1-5 use NtSetSystemInformation and need administrator rights plus the
SeProfileSingleProcessPrivilege / SeIncreaseQuotaPrivilege privileges. Without admin
rights only a per-process working-set trim is possible, which changes little.
"""
import os
import sys
import time

from .i18n import tr

# NtSetSystemInformation classes / commands (from the Windows DDK, as used by Mem Reduct)
SYSTEM_FILE_CACHE_INFORMATION_EX = 81
SYSTEM_MEMORY_LIST_INFORMATION = 80
SYSTEM_COMBINE_PHYSICAL_MEMORY_INFORMATION = 130
MEMORY_EMPTY_WORKING_SETS = 2
MEMORY_FLUSH_MODIFIED_LIST = 3
MEMORY_PURGE_STANDBY_LIST = 4
MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST = 5

STATUS_PRIVILEGE_NOT_HELD = 0xC0000061


def is_windows():
    return sys.platform == "win32"


def is_admin():
    if not is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _helper_command(result_path, purge_standby, extra=()):
    """Executable + arguments that run only the RAM cleanup (see main.py --clean-ram)."""
    args = ["--clean-ram", result_path] + (["--purge-standby"] if purge_standby else []) + list(extra)
    if getattr(sys, "frozen", False):
        executable = sys.executable
    else:
        # pythonw.exe avoids flashing a console window.
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        executable = pythonw if os.path.exists(pythonw) else sys.executable
        main_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
        args = [main_script] + args
    return executable, subprocess_list2cmdline(args)


def subprocess_list2cmdline(args):
    import subprocess
    return subprocess.list2cmdline(args)


# ---------------------------------------------------------------------------
# One-time administrator approval.
#
# The first cleanup asks Windows for administrator permission (UAC). That elevated helper
# also registers a hidden Task Scheduler task that runs the same cleanup with highest
# privileges. Starting an existing task needs no permission prompt, so every later
# cleanup (button or memory alert) runs silently through the task.

TASK_NAME = r"\SystemResourceMonitor\CleanRAM"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def _app_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SystemResourceMonitor")


def _task_result_path():
    return os.path.join(_app_dir(), "clean_result.txt")


def _task_command():
    """Command the scheduled task runs; purge setting is read from config at run time."""
    return _helper_command(_task_result_path(), False, ["--purge-from-config"])


def _schtasks(*args, timeout=30):
    import subprocess
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          timeout=timeout, creationflags=_NO_WINDOW)


def _load_config():
    from .ai_insights import load_config
    return load_config()


def _save_config_value(key, value):
    from .ai_insights import load_config, save_config
    config = load_config()
    if value is None:
        config.pop(key, None)
    else:
        config[key] = value
    save_config(config)


def task_ready():
    """True if the silent cleanup task exists and points at this copy of the app."""
    if not is_windows():
        return False
    executable, params = _task_command()
    if _load_config().get("clean_task_command") != f"{executable} {params}":
        return False
    try:
        return _schtasks("/query", "/tn", TASK_NAME).returncode == 0
    except Exception:
        return False


def register_task():
    """Create/replace the task. Must run with administrator rights. Returns an error or None."""
    import tempfile
    from xml.sax.saxutils import escape
    executable, params = _task_command()
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    user_id = f"{domain}\\{user}" if domain else user
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>System Resource Monitor: RAM cleanup without a UAC prompt</Description>
  </RegistrationInfo>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <AllowHardTerminate>true</AllowHardTerminate>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(executable)}</Command>
      <Arguments>{escape(params)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""
    handle, xml_path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    try:
        with open(xml_path, "w", encoding="utf-16") as xml_file:
            xml_file.write(xml)
        result = _schtasks("/create", "/tn", TASK_NAME, "/xml", xml_path, "/f")
        if result.returncode != 0:
            return (result.stderr or result.stdout or "schtasks failed").strip()
        _save_config_value("clean_task_command", f"{executable} {params}")
        return None
    except Exception as exc:
        return str(exc)
    finally:
        try:
            os.remove(xml_path)
        except OSError:
            pass


def remove_task():
    """Delete the task (used by the uninstaller and when it is no longer valid)."""
    try:
        _schtasks("/delete", "/tn", TASK_NAME, "/f")
    except Exception:
        pass
    _save_config_value("clean_task_command", None)


def _run_task(timeout_seconds=90):
    """Run the cleanup through the task. Returns the result text, or None if it did not work."""
    result_path = _task_result_path()
    try:
        os.remove(result_path)
    except OSError:
        pass
    try:
        if _schtasks("/run", "/tn", TASK_NAME).returncode != 0:
            return None
    except Exception:
        return None
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(0.3)
        try:
            with open(result_path, "r", encoding="utf-8") as result_file:
                text = result_file.read().strip()
            if text:
                return text
        except OSError:
            continue
    return None


def clean_memory_elevated(purge_standby=True, timeout_seconds=120):
    """Run the cleanup with administrator rights, asking Windows (UAC) only if needed."""
    if not is_windows():
        return tr("memory cleanup is only available on Windows")
    if is_admin():
        return clean_memory(purge_standby)
    if task_ready():
        result = _run_task()
        if result:
            return result
        # The task did not answer (deleted, moved app, ...): fall back to asking once more.

    import ctypes
    import tempfile
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle, result_path = tempfile.mkstemp(prefix="srm-clean-", suffix=".txt")
    os.close(handle)
    try:
        executable, params = _helper_command(result_path, purge_standby, ["--register-task"])
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = params
        info.nShow = 0  # SW_HIDE
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            if ctypes.get_last_error() == 1223:  # ERROR_CANCELLED
                return tr("cancelled: administrator permission was not granted")
            return tr("could not start the cleanup (error {code})").format(code=ctypes.get_last_error())
        if info.hProcess:
            kernel32.WaitForSingleObject(info.hProcess, timeout_seconds * 1000)
            kernel32.CloseHandle(info.hProcess)
        try:
            with open(result_path, "r", encoding="utf-8") as result_file:
                text = result_file.read().strip()
        except OSError:
            text = ""
        return text or tr("the cleanup finished without a result (it may have timed out)")
    finally:
        try:
            os.remove(result_path)
        except OSError:
            pass


def run_cli(args):
    """Entry point for the elevated helper: main.py --clean-ram <result file> [--purge-standby]."""
    result_path = args[0] if args else None
    purge = "--purge-standby" in args
    if "--purge-from-config" in args:
        try:
            from .alerts import load_settings
            purge = bool(load_settings().get("purge_standby", True))
        except Exception:
            purge = True
    note = ""
    if "--register-task" in args and is_admin():
        error = register_task()
        if error:
            note = tr("; silent cleanup could not be set up: {error}").format(error=error)
    try:
        result = clean_memory(purge_standby=purge) + note
    except Exception as exc:
        result = tr("memory cleanup failed: {error}").format(error=exc)
    if result_path:
        with open(result_path, "w", encoding="utf-8") as result_file:
            result_file.write(result)
    else:
        print(result)


def _memory_percent():
    import psutil
    vm = psutil.virtual_memory()
    return vm.percent, vm.total - vm.available


def _enable_privileges(names):
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                               ctypes.POINTER(TOKEN_PRIVILEGES), wintypes.DWORD,
                                               ctypes.c_void_p, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    token = wintypes.HANDLE()
    TOKEN_ADJUST_PRIVILEGES, TOKEN_QUERY, SE_PRIVILEGE_ENABLED = 0x20, 0x08, 0x02
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return []
    enabled = []
    try:
        for name in names:
            luid = LUID()
            if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
                continue
            privileges = TOKEN_PRIVILEGES(1, (LUID_AND_ATTRIBUTES * 1)(
                LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)))
            ctypes.set_last_error(0)
            advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
            if ctypes.get_last_error() == 0:  # 1300 = ERROR_NOT_ALL_ASSIGNED
                enabled.append(name)
    finally:
        kernel32.CloseHandle(token)
    return enabled


def _nt_set(info_class, buffer):
    import ctypes
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtSetSystemInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
    ntdll.NtSetSystemInformation.restype = ctypes.c_long
    status = ntdll.NtSetSystemInformation(info_class, ctypes.byref(buffer), ctypes.sizeof(buffer))
    return status & 0xFFFFFFFF


def _memory_list_command(command):
    import ctypes
    return _nt_set(SYSTEM_MEMORY_LIST_INFORMATION, ctypes.c_int(command)) == 0


def _flush_file_cache():
    import ctypes
    from ctypes import wintypes

    class SYSTEM_FILECACHE_INFORMATION(ctypes.Structure):
        _fields_ = [("CurrentSize", ctypes.c_size_t), ("PeakSize", ctypes.c_size_t),
                    ("PageFaultCount", wintypes.ULONG), ("MinimumWorkingSet", ctypes.c_size_t),
                    ("MaximumWorkingSet", ctypes.c_size_t), ("CurrentSizeIncludingTransitionInPages", ctypes.c_size_t),
                    ("PeakSizeIncludingTransitionInPages", ctypes.c_size_t),
                    ("TransitionRePurposeCount", wintypes.ULONG), ("Flags", wintypes.ULONG)]

    info = SYSTEM_FILECACHE_INFORMATION()
    info.MinimumWorkingSet = ctypes.c_size_t(-1).value
    info.MaximumWorkingSet = ctypes.c_size_t(-1).value
    return _nt_set(SYSTEM_FILE_CACHE_INFORMATION_EX, info) == 0


def _combine_pages():
    import ctypes

    class MEMORY_COMBINE_INFORMATION_EX(ctypes.Structure):
        _fields_ = [("Handle", ctypes.c_void_p), ("PagesCombined", ctypes.c_size_t),
                    ("Flags", ctypes.c_ulong)]

    return _nt_set(SYSTEM_COMBINE_PHYSICAL_MEMORY_INFORMATION, MEMORY_COMBINE_INFORMATION_EX()) == 0


def _trim_each_process():
    """Fallback without admin rights: EmptyWorkingSet on every process we can open."""
    import ctypes
    from ctypes import wintypes
    import psutil
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    count = 0
    for proc in psutil.process_iter(["pid"]):
        if proc.pid in (0, 4):
            continue
        handle = kernel32.OpenProcess(0x0400 | 0x0100, False, proc.pid)
        if handle:
            try:
                count += bool(psapi.EmptyWorkingSet(handle))
            finally:
                kernel32.CloseHandle(handle)
    return count


def clean_memory(purge_standby=True):
    """Run the cleanup. Returns a one-line summary (before -> after)."""
    if not is_windows():
        return tr("memory cleanup is only available on Windows")
    before_percent, before_used = _memory_percent()
    done, skipped = [], []

    if is_admin():
        _enable_privileges(["SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege"])
        steps = [("working sets", lambda: _memory_list_command(MEMORY_EMPTY_WORKING_SETS)),
                 ("file cache", _flush_file_cache),
                 ("modified list", lambda: _memory_list_command(MEMORY_FLUSH_MODIFIED_LIST))]
        if purge_standby:
            steps += [("low-priority standby", lambda: _memory_list_command(MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST)),
                      ("standby list", lambda: _memory_list_command(MEMORY_PURGE_STANDBY_LIST))]
        steps.append(("page combining", _combine_pages))
        for name, step in steps:
            try:
                (done if step() else skipped).append(tr(name))
            except Exception:
                skipped.append(tr(name))
    else:
        count = _trim_each_process()
        done.append(tr("working sets of {count} apps").format(count=count))
        skipped.append(tr("system memory lists (administrator permission needed)"))

    time.sleep(0.7)
    after_percent, after_used = _memory_percent()
    freed_mb = max(0, before_used - after_used) / (1024 * 1024)
    summary = tr("RAM {before}% -> {after}% (freed {freed} MB)").format(
        before=f"{before_percent:.0f}", after=f"{after_percent:.0f}", freed=f"{freed_mb:.0f}")
    if skipped:
        summary += tr("; skipped: {steps}").format(steps=", ".join(skipped))
    return summary
