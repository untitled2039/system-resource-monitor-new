import tkinter as tk
import customtkinter as ctk
from tkinter import ttk
from collections import deque
import threading
from tkinter import messagebox
from utils.utils import export_data
from .monitor import monitor_resources
from .gui import create_gui
import psutil
import queue
import time
import gc
import heapq
import sys
from .remote_link import PairingServer, TCP_PORT, local_ipv4_addresses
from . import ai_insights
from . import i18n
from .i18n import tr
from .alerts import AlertTracker, load_settings, save_settings, notify
from . import memory_cleaner
from .history import HistoryStore, LOCAL_DEVICE
from .tray import TrayIcon, set_autostart

class ResourceMonitor:
    SESSION_SAMPLES = 3600  # in-memory samples kept for export fallback (about 1 hour)

    def __init__(self, current_version):
        self.CURRENT_VERSION = current_version
        self.alert_settings = load_settings()
        self.alert_tracker = AlertTracker()
        self.CPU_THRESHOLD = self.alert_settings["cpu"]
        self.MEMORY_THRESHOLD = self.alert_settings["memory"]
        self.GPU_THRESHOLD = self.alert_settings["gpu"]
        self.HISTORY_LENGTH = 60
        self.CPU_MON_INTERVAL = self.alert_settings["interval_seconds"]

        self.cpu_history = deque(maxlen=self.HISTORY_LENGTH)
        self.memory_history = deque(maxlen=self.HISTORY_LENGTH)
        self.gpu_history = deque(maxlen=self.HISTORY_LENGTH)
        self.gpu_memory_history = deque(maxlen=self.HISTORY_LENGTH)
        self.time_history = deque(maxlen=self.HISTORY_LENGTH)

        # Capped: long-term data lives in the SQLite history, so RAM no longer grows over days.
        self.all_cpu_history = deque(maxlen=self.SESSION_SAMPLES)
        self.all_memory_history = deque(maxlen=self.SESSION_SAMPLES)
        self.all_gpu_history = deque(maxlen=self.SESSION_SAMPLES)
        self.all_gpu_memory_history = deque(maxlen=self.SESSION_SAMPLES)
        self.all_time_history = deque(maxlen=self.SESSION_SAMPLES)

        self.monitoring = False
        self.remote_client = None
        self.remote_device_name = None
        self.pairing_server = None
        self.pairing_dialog = None
        self.latest_processes = []
        self._insight_busy = False
        self._auto_insight_job = None
        self._windowed_geometry = None
        self._tray_hint_shown = False
        self._window_visible = True
        self._process_rows = []
        self._process_dirty = False
        self._history_rows = []
        self._history_since = 0.0
        self._auto_cleaning = False
        self._history_canvas = None
        self._history_error = ""
        try:
            self.history = HistoryStore()
        except Exception as exc:  # e.g. AppData not writable
            self.history, self._history_error = None, str(exc)
        self.process_queue = queue.Queue(maxsize=1)  # only the newest list is kept
        self.process_monitoring_thread = None
        self.theme_mode = "dark"
        self.good_color = "#9ece6a"
        self.bad_color = "#f7768e"

        self.root = ctk.CTk()
        self.root.title("System Resource Monitor v2.0")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.minsize(min(900, screen_width), min(700, screen_height))
        self.is_fullscreen = False
        self.root.bind_all("<F11>", self.toggle_fullscreen)
        self.root.bind_all("<Escape>", self.exit_fullscreen)

        # Modern styling
        self.setup_styles()

        # Center the window
        window_width = 1000
        window_height = 850
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 3
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')

        # Create GUI
        create_gui(self)
        self.tray = TrayIcon(self)
        self.tray.start()
        self.root.after(1500, self._history_tick)
        self.root.after(300_000, self._idle_trim_tick)

    def _monitor_rect(self):
        """Physical pixel rectangle of the monitor the window is on (Windows), else screen size."""
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HMONITOR
            user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
            hwnd = int(self.root.wm_frame(), 16)
            monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                rect = info.rcMonitor
                return hwnd, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
        return None, 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _stretch_to_monitor(self):
        # Tk reads the screen size before customtkinter enables high-DPI mode, so on a
        # scaled display (e.g. 125%) its fullscreen covers only 1/scale of the monitor.
        # Resize the window to the monitor's real pixel size.
        if not self.is_fullscreen:
            return
        hwnd, x, y, width, height = self._monitor_rect()
        if hwnd is None:
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
            swp_nozorder, swp_framechanged, swp_showwindow = 0x0004, 0x0020, 0x0040
            user32.SetWindowPos(hwnd, None, x, y, width, height,
                                swp_nozorder | swp_framechanged | swp_showwindow)
        except Exception:
            pass

    def _set_fullscreen(self, enabled):
        if enabled == self.is_fullscreen:
            return
        self.is_fullscreen = enabled
        if enabled:
            self._windowed_geometry = tk.Tk.wm_geometry(self.root)
            self.root.attributes("-fullscreen", True)
            self.root.after(60, self._stretch_to_monitor)
        else:
            self.root.attributes("-fullscreen", False)
            if self._windowed_geometry:
                tk.Tk.wm_geometry(self.root, self._windowed_geometry)
        if hasattr(self, "fullscreen_toggle_button"):
            self.fullscreen_toggle_button.configure(
                text=tr("Windowed") if enabled else tr("Fullscreen"))

    def toggle_fullscreen(self, _event=None):
        self._set_fullscreen(not self.is_fullscreen)
        return "break"

    def exit_fullscreen(self, _event=None):
        if self.pairing_dialog and self.pairing_dialog.winfo_exists():
            picker_path = str(self.pairing_dialog)
            if _event is not None:
                widget_path = str(_event.widget)
                if widget_path == picker_path or widget_path.startswith(picker_path + "."):
                    return "break"
        if self.is_fullscreen:
            self._set_fullscreen(False)
            return "break"

    def setup_styles(self):
        """Setup modern styling for the application"""
        style = ttk.Style()

        # Configure modern theme
        style.theme_use('clam')

        # Define modern colors
        bg_color = '#f0f0f0'
        accent_color = '#0078d4'
        text_color = '#323130'

        # Configure styles
        style.configure('Title.TLabel', font=('Segoe UI', 12, 'bold'), foreground=text_color)
        style.configure('Modern.TButton', padding=(10, 5))
        style.configure('Card.TFrame', relief='flat', borderwidth=1)

        self.root.configure(bg=bg_color)

    def toggle_theme(self):
        dark_to_light = {
            "#0f1117": "#f5f7fb", "#1a1b26": "#ffffff", "#20222e": "#edf1f7",
            "#7aa2f7": "#315fb8", "#c0caf5": "#202b3c", "#565f89": "#667085",
            "#9ece6a": "#21804a", "#f7768e": "#c13753", "#5d84d4": "#4f79cc",
            "#2c2f3f": "#dde4f0", "#16171f": "#f5f7fb", "#ff9e64": "#b85c18",
            "#bb9af7": "#6941a5", "#33415c": "#dae5f7", "#2b3040": "#e5eaf2",
            "#34384a": "#cad3e0", "#8b93b8": "#475569",
            "#a9b2d0": "#475569", "#dbe2ee": "#2b3040",
            "#107c10": "#21804a", "#d13438": "#c13753",
        }
        if self.theme_mode == "dark":
            mapping = dark_to_light
            self.theme_mode = "light"
            self.good_color, self.bad_color = "#21804a", "#c13753"
            self.theme_toggle_button.configure(text=tr("Dark"))
        else:
            mapping = {light: dark for dark, light in dark_to_light.items()}
            self.theme_mode = "dark"
            self.good_color, self.bad_color = "#9ece6a", "#f7768e"
            self.theme_toggle_button.configure(text=tr("Light"))
        ctk.set_appearance_mode(self.theme_mode)

        color_options = (
            "fg_color", "text_color", "border_color", "hover_color",
            "text_color_disabled", "disabled_fg_color",
            "scrollbar_button_color", "scrollbar_button_hover_color",
            "segmented_button_fg_color", "segmented_button_selected_color",
            "segmented_button_selected_hover_color",
        )
        def recolor(widget):
            for option in color_options:
                try:
                    value = widget.cget(option)
                    if isinstance(value, str) and value.lower() in mapping:
                        widget.configure(**{option: mapping[value.lower()]})
                except (ValueError, tk.TclError):
                    pass
            for child in widget.winfo_children():
                recolor(child)
        recolor(self.root)
        if self.pairing_dialog and self.pairing_dialog.winfo_exists():
            recolor(self.pairing_dialog)
        self._process_dirty = True
        if self._history_canvas is not None:
            self.refresh_history()

    def _publish_processes(self, processes):
        """Keep only the newest process list (older ones are dropped, not queued up)."""
        try:
            while True:
                self.process_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self.process_queue.put_nowait(processes)
        except queue.Full:
            pass

    def _ensure_process_rows(self):
        """Create the 20 row widgets once; later refreshes only change their text."""
        if self._process_rows:
            return
        font_row = ctk.CTkFont(family="Segoe UI", size=13)
        font_mono = ctk.CTkFont(family="Consolas", size=12, weight="bold")
        for _ in range(20):
            card = ctk.CTkFrame(self.process_scroll_frame, corner_radius=8, height=40)
            card.pack_propagate(False)
            pid = ctk.CTkLabel(card, text="", font=font_mono, width=80, anchor="w")
            pid.pack(side="left", padx=(12, 0))
            name = ctk.CTkLabel(card, text="", font=font_row, anchor="w")
            name.pack(side="left", expand=True, fill="x", padx=10)
            mem = ctk.CTkLabel(card, text="", font=font_row, width=120, anchor="e")
            mem.pack(side="right", padx=10)
            cpu = ctk.CTkLabel(card, text="", font=font_row, width=120, anchor="e")
            cpu.pack(side="right", padx=(0, 10))
            self._process_rows.append((card, pid, name, mem, cpu))

    def _render_process_rows(self):
        self._ensure_process_rows()
        dark = self.theme_mode == "dark"
        main_text = "#c0caf5" if dark else "#202b3c"
        mem_color = "#9ece6a" if dark else "#21804a"
        cpu_color = "#7aa2f7" if dark else "#315fb8"
        processes = self.latest_processes[:20]
        for idx, (card, pid, name, mem, cpu) in enumerate(self._process_rows):
            if idx >= len(processes):
                if card.winfo_manager():
                    card.pack_forget()
                continue
            proc = processes[idx]
            row_bg = (("#1a1b26" if idx % 2 == 0 else "#20222e") if dark
                      else ("#ffffff" if idx % 2 == 0 else "#edf1f7"))
            card.configure(fg_color=row_bg)
            pid.configure(text="—" if proc.get('pid') is None else str(proc['pid']), text_color=main_text)
            name.configure(text=str(proc.get('name')), text_color=main_text)
            mem.configure(text="—" if proc.get('memory_percent') is None else f"{proc['memory_percent']:.2f}%",
                          text_color=mem_color)
            cpu.configure(text=("—" if proc.get('cpu_percent_normalized') is None
                                else f"{proc['cpu_percent_normalized']:.2f}%"), text_color=cpu_color)
            if not card.winfo_manager():
                card.pack(fill="x", pady=3, padx=2)

    def update_process_info(self):
        try:
            try:
                processes = self.process_queue.get_nowait()
            except queue.Empty:
                processes = None
            if processes is not None:
                self.latest_processes = list(processes)
                self._process_dirty = True
            if (self._process_dirty and self._window_visible
                    and self.tab_control.get() == tr("🔧 Top Processes")):
                self._render_process_rows()
                self._process_dirty = False
        except Exception:
            pass
        self.root.after(1000, self.update_process_info)

    def export_top_processes(self):
        """Export the current list of processes to a file."""
        try:
            process_text = self.process_list.get(1.0, tk.END).strip()

            if not process_text:
                messagebox.showwarning(tr("Export Failed"), tr("No processes to export."))
                return

            with open("top_processes.txt", "w") as file:
                file.write(process_text)
                messagebox.showinfo(tr("Export Successful"),
                                    tr("Processes exported to 'top_processes.txt'"))

        except Exception as e:
            messagebox.showerror(tr("Export Failed"),
                                 tr("An error occurred while exporting: {error}").format(error=e))

    def start_monitoring(self):
        if not self.monitoring:
            self.monitoring = True

            # Start monitoring threads
            self.monitor_thread = threading.Thread(target=monitor_resources,
                                                 args=(self,), daemon=True)
            self.monitor_thread.start()

            if hasattr(self, 'monitor_top_processes'):
                self.process_monitoring_thread = threading.Thread(
                    target=self.monitor_top_processes, daemon=True)
                self.process_monitoring_thread.start()

            # Update GUI state
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.status_label.configure(text=tr("🟢 Monitoring Active"),
                                   text_color=self.good_color)

    def stop_monitoring(self):
        self.monitoring = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text=tr("🔴 Monitoring Stopped"),
                               text_color=self.bad_color)

    def _call_on_ui_thread(self, callback, timeout=120):
        completed = threading.Event()
        result = {}
        def run():
            try:
                result["value"] = callback()
            except Exception as exc:
                result["error"] = exc
            finally:
                completed.set()
        self.root.after(0, run)
        if not completed.wait(timeout):
            return None
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def open_pairing_dialog(self):
        """Show a 5-digit code and wait for an Android / Raspberry Pi agent to enter it."""
        if self.pairing_dialog and self.pairing_dialog.winfo_exists():
            self.pairing_dialog.focus_force()
            return
        dark = self.theme_mode == "dark"
        text_color = "#c0caf5" if dark else "#202b3c"
        dim_color = "#a9b2d0" if dark else "#475569"
        accent = "#7aa2f7" if dark else "#315fb8"
        dialog = ctk.CTkToplevel(self.root)
        self.pairing_dialog = dialog
        dialog.title(tr("Connect a device"))
        dialog.geometry("460x400")
        dialog.resizable(False, False)
        dialog.configure(fg_color="#0f1117" if dark else "#f5f7fb")
        dialog.transient(self.root)

        ctk.CTkLabel(dialog, text=tr("Enter this code on your device"),
                     font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
                     text_color=text_color).pack(pady=(22, 4))
        ctk.CTkLabel(dialog, text=tr("Android app or Raspberry Pi agent, on the same Wi-Fi / LAN"),
                     text_color=dim_color).pack()
        self.pairing_code_label = ctk.CTkLabel(
            dialog, text="-----", text_color=accent,
            font=ctk.CTkFont(family="Consolas", size=56, weight="bold"))
        self.pairing_code_label.pack(pady=(18, 6))
        self.pairing_status_label = ctk.CTkLabel(
            dialog, text=tr("Starting..."), text_color=dim_color, wraplength=420)
        self.pairing_status_label.pack(pady=(0, 6))
        progress = ctk.CTkProgressBar(dialog, mode="indeterminate", height=6, progress_color=accent)
        progress.pack(fill="x", padx=40, pady=(0, 10))
        progress.start()
        addresses = ", ".join(local_ipv4_addresses()) or "unknown"
        ctk.CTkLabel(dialog, text=tr("This PC: {addresses}  (port {port})").format(addresses=addresses, port=TCP_PORT),
                     text_color=dim_color, font=ctk.CTkFont(size=11)).pack()

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=18, pady=16)
        new_code_button = ctk.CTkButton(footer, text=tr("New code"), width=110)
        new_code_button.pack(side="left")
        ctk.CTkButton(footer, text=tr("Cancel"), width=100,
                      fg_color="#565f89" if dark else "#667085",
                      command=dialog.destroy).pack(side="right")

        def ui(callback):
            def run():
                if dialog.winfo_exists():
                    callback()
            try:
                self.root.after(0, run)
            except Exception:
                pass

        def on_code(code):
            ui(lambda: (self.pairing_code_label.configure(text=code),
                        self.pairing_status_label.configure(text=tr("Waiting for a device to connect..."))))

        def on_failed(count):
            ui(lambda: self.pairing_status_label.configure(
                text=tr("A device entered a wrong code ({count}/5). After 5 wrong attempts a new code is generated.").format(count=count)))

        def on_error(message):
            ui(lambda: (progress.stop(),
                        self.pairing_status_label.configure(text=message, text_color=self.bad_color)))

        def on_connected(connection):
            def finish():
                if self.remote_client:
                    self.remote_client.close()
                self.remote_client, self.remote_device_name = connection, connection.name
                self.remote_status_label.configure(text=tr("Connected: {name}").format(name=connection.name),
                                                   text_color=self.good_color)
                self.remote_disconnect_button.configure(state="normal")
                self.process_title_label.configure(text=tr("Top 20 Processes — {name}").format(name=connection.name))
                if dialog.winfo_exists():
                    dialog.destroy()
            self.root.after(0, finish)

        server = PairingServer(on_code=on_code, on_connected=on_connected,
                               on_error=on_error, on_attempt_failed=on_failed)
        self.pairing_server = server
        new_code_button.configure(command=server.regenerate_code)

        def on_destroy(event):
            if event.widget is dialog:
                server.stop()
                if self.pairing_dialog is dialog:
                    self.pairing_dialog = None
                    self.pairing_server = None
        dialog.bind("<Destroy>", on_destroy)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        threading.Thread(target=server.start, daemon=True).start()

    def disconnect_remote_device(self):
        if self.remote_client:
            self.remote_client.close()
            self.remote_client = None
            self.remote_device_name = None
        self.remote_status_label.configure(text=tr("Not connected"), text_color="#565f89")
        self.remote_disconnect_button.configure(state="disabled")
        self.process_title_label.configure(text=tr("Top 20 Processes by CPU Usage"))

    # ---------------- Window, tray and startup ----------------

    def on_close(self):
        """Window X button: hide to the tray (if enabled and available) or quit."""
        if self.alert_settings.get("minimize_to_tray") and self.tray.available:
            self.root.withdraw()
            self._window_visible = False
            self.root.after(2000, self._trim_own_memory)
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.notify(tr("System Resource Monitor"),
                                 tr("Still running in the tray. Right-click the tray icon to quit."))
        else:
            self.quit_app()

    def show_window(self):
        self._window_visible = True
        self._process_dirty = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self):
        self.cleanup()

    def _set_status(self, active):
        self.status_label.configure(
            text=tr("● Monitoring Active") if active else tr("● Monitoring Stopped"),
            text_color=self.good_color if active else self.bad_color)

    def toggle_monitoring_from_tray(self):
        if self.monitoring:
            self.stop_monitoring()
            self._set_status(False)
        else:
            self.start_monitoring()
            self._set_status(True)
        self.tray.refresh()

    def launch_minimized(self):
        """Started by Windows at sign-in: monitor in the background."""
        self.start_monitoring()
        self._set_status(True)
        if self.tray.available:
            self.root.withdraw()
            self._window_visible = False
            self.root.after(5000, self._trim_own_memory)

    def _trim_own_memory(self):
        """While hidden: free Python garbage and hand unused pages of this app back to Windows."""
        gc.collect()
        if sys.platform != "win32":
            return
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetProcessWorkingSetSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
            kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(),
                                              ctypes.c_size_t(-1).value, ctypes.c_size_t(-1).value)
        except Exception:
            pass

    def _idle_trim_tick(self):
        if not self._window_visible:
            self._trim_own_memory()
        self.root.after(300_000, self._idle_trim_tick)

    def save_background_options(self):
        self.alert_settings["minimize_to_tray"] = bool(self.tray_switch.get())
        try:
            save_settings(self.alert_settings)
        except OSError:
            pass

    def toggle_autostart(self):
        enabled = bool(self.autostart_switch.get())
        try:
            set_autostart(enabled)
        except OSError as exc:
            self.settings_status_label.configure(
                text=tr("Could not change Windows startup: {error}").format(error=exc),
                text_color=self.bad_color)
            if enabled:
                self.autostart_switch.deselect()
            else:
                self.autostart_switch.select()

    # ---------------- History ----------------

    def _history_devices(self):
        """Display name -> device key, newest first, always including this PC."""
        devices = self.history.devices() if self.history else []
        if LOCAL_DEVICE not in devices:
            devices.insert(0, LOCAL_DEVICE)
        return {(tr("this PC") if key == LOCAL_DEVICE else key): key for key in devices}

    def _history_selection(self):
        devices = self._history_devices()
        names = list(devices)
        current = self.history_device_menu.get()
        self.history_device_menu.configure(values=names)
        if current not in devices:
            current = names[0]
            self.history_device_menu.set(current)
        spans = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
        range_label = self.history_range.get() or "24h"
        return devices[current], current, time.time() - spans.get(range_label, 86400), range_label

    def refresh_history(self):
        if not self.history:
            self.history_stats_label.configure(
                text=tr("History is unavailable: {error}").format(error=self._history_error))
            return
        self.history.flush()
        device, _name, since, _range = self._history_selection()
        stats = self.history.stats(device, since)
        if stats:
            fmt = lambda value: "—" if value is None else f"{value:.1f}"
            text = tr("CPU avg {cpu}% · peak {cpu_peak}%    Memory avg {mem}% · peak {mem_peak}%").format(
                cpu=fmt(stats["cpu"]["avg"]), cpu_peak=fmt(stats["cpu"]["max"]),
                mem=fmt(stats["memory"]["avg"]), mem_peak=fmt(stats["memory"]["max"]))
            if stats["gpu"]["max"]:
                text += "    " + tr("GPU avg {gpu}% · peak {gpu_peak}%").format(
                    gpu=fmt(stats["gpu"]["avg"]), gpu_peak=fmt(stats["gpu"]["max"]))
        else:
            text = tr("No history in this period yet.")
        self.history_stats_label.configure(text=text)
        self._draw_history_chart(self.history.series(device, since), since)

    def _draw_history_chart(self, rows, since):
        """Line chart drawn on a plain tk.Canvas (no matplotlib/numpy: about 50 MB less RAM)."""
        if self._history_canvas is None:
            canvas = tk.Canvas(self.history_chart_frame, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True, padx=10, pady=10)
            canvas.bind("<Configure>", lambda _event: self._render_history_chart())
            self._history_canvas = canvas
        self._history_rows, self._history_since = rows, since
        self._render_history_chart()

    def _render_history_chart(self):
        canvas = self._history_canvas
        if canvas is None:
            return
        dark = self.theme_mode == "dark"
        background = "#20222e" if dark else "#edf1f7"
        foreground = "#c0caf5" if dark else "#202b3c"
        grid = "#34384a" if dark else "#cad3e0"
        canvas.configure(bg=background)
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 120 or height < 80:
            return
        left, right, top, bottom = 46, 16, 30, 26
        plot_w, plot_h = width - left - right, height - top - bottom
        small = ("Segoe UI", 9)
        for value in (0, 25, 50, 75, 100):
            y = top + plot_h * (1 - value / 100)
            canvas.create_line(left, y, width - right, y, fill=grid)
            canvas.create_text(left - 6, y, text=f"{value}%", anchor="e", fill=foreground, font=small)
        rows = self._history_rows
        if not rows:
            canvas.create_text(width / 2, height / 2, text=tr("No data"), fill=foreground, font=("Segoe UI", 11))
            return
        start, end = self._history_since, time.time()
        span = max(1.0, end - start)
        x_of = lambda t: left + (t - start) / span * plot_w
        y_of = lambda v: top + plot_h * (1 - max(0.0, min(100.0, v)) / 100)
        gap = max(60.0, span / 600 * 3)  # break the line where the app was not running
        series = [(1, "CPU", "#7aa2f7" if dark else "#315fb8"),
                  (2, tr("Memory"), "#9ece6a" if dark else "#21804a")]
        if any(row[3] for row in rows if row[3]):
            series.append((3, "GPU", "#ff9e64" if dark else "#b85c18"))
        for index, _label, color in series:
            points, last_t = [], None
            for row in rows:
                value = row[index]
                if value is None or (last_t is not None and row[0] - last_t > gap):
                    if len(points) >= 4:
                        canvas.create_line(*points, fill=color, width=2)
                    points = []
                if value is not None:
                    points += [x_of(row[0]), y_of(value)]
                last_t = row[0]
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2)
            elif len(points) == 2:
                canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2, fill=color, outline=color)
        x = left
        for _index, label, color in series:
            canvas.create_line(x, 12, x + 16, 12, fill=color, width=3)
            item = canvas.create_text(x + 22, 12, text=label, anchor="w", fill=foreground, font=small)
            bbox = canvas.bbox(item)
            x = (bbox[2] if bbox else x + 60) + 18
        time_format = "%H:%M" if span <= 2 * 86400 else "%m-%d"
        for i in range(5):
            t = start + span * i / 4
            anchor = "nw" if i == 0 else ("ne" if i == 4 else "n")
            canvas.create_text(x_of(t), height - bottom + 6, text=time.strftime(time_format, time.localtime(t)),
                               anchor=anchor, fill=foreground, font=small)

    def _history_tick(self):
        """Refresh the History tab once a minute while it is visible."""
        try:
            if self.tab_control.get() == tr("📈 History") and self.root.state() != "withdrawn":
                self.refresh_history()
        except Exception:
            pass
        self.root.after(60_000, self._history_tick)

    def analyze_history_period(self):
        if not self.history:
            return
        self.history.flush()
        device, name, since, range_label = self._history_selection()
        data = ai_insights.build_period_snapshot(self.history, device, name, since, range_label)

        def show(text):
            self.history_ai_text.configure(state="normal")
            self.history_ai_text.delete("1.0", "end")
            self.history_ai_text.insert("1.0", text)
            self.history_ai_text.configure(state="disabled")

        if not data or not ai_insights.active_ai():
            show(ai_insights.local_period_summary(data))
            return
        self.history_ai_button.configure(state="disabled", text=tr("Analyzing..."))

        def work():
            try:
                text = ai_insights.summarize(data, kind="period")
            except Exception as exc:
                text = (ai_insights.local_period_summary(data) +
                        tr("\n\n(AI analysis failed: {error}. Showing built-in analysis.)").format(error=exc))

            def finish():
                self.history_ai_button.configure(state="normal", text=tr("Analyze this period"))
                show(text)
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    # ---------------- Settings & alerts ----------------

    def save_settings_from_ui(self):
        limits = {"cpu": (1, 100), "memory": (1, 100), "gpu": (1, 100), "gpu_memory": (1, 100),
                  "duration_seconds": (0, 3600), "cooldown_minutes": (0, 1440),
                  "interval_seconds": (0.5, 60), "history_days": (1, 365)}
        new_settings = dict(self.alert_settings)
        labels = {"cpu": "CPU limit (%)", "memory": "Memory limit (%)", "gpu": "GPU limit (%)",
                  "gpu_memory": "GPU memory limit (%)", "duration_seconds": "Alert after (s)",
                  "cooldown_minutes": "Repeat after (min)", "interval_seconds": "Update interval (s)",
                  "history_days": "Keep history (days)"}

        def field_name(key):
            return tr(labels.get(key, key))

        for key, entry in self.settings_entries.items():
            low, high = limits[key]
            try:
                value = float(entry.get().strip())
            except ValueError:
                self.settings_status_label.configure(
                    text=tr("Enter a number for every field ({field}).").format(field=field_name(key)),
                    text_color=self.bad_color)
                return
            if not low <= value <= high:
                self.settings_status_label.configure(
                    text=tr("{field}: use a value between {low} and {high}.").format(
                        field=field_name(key), low=f"{low:g}", high=f"{high:g}"),
                    text_color=self.bad_color)
                return
            new_settings[key] = int(value) if key in ("duration_seconds", "cooldown_minutes", "history_days") else value
        new_settings["alerts_enabled"] = bool(self.alerts_enabled_switch.get())
        new_settings["purge_standby"] = bool(self.purge_standby_switch.get())
        self.alert_settings = new_settings
        self.CPU_THRESHOLD = new_settings["cpu"]
        self.MEMORY_THRESHOLD = new_settings["memory"]
        self.GPU_THRESHOLD = new_settings["gpu"]
        self.CPU_MON_INTERVAL = new_settings["interval_seconds"]
        self.alert_tracker.reset()
        try:
            save_settings(new_settings)
            self.settings_status_label.configure(text=tr("Saved."), text_color=self.good_color)
        except OSError as exc:
            self.settings_status_label.configure(
                text=tr("Applied, but could not save to disk: {error}").format(error=exc),
                text_color=self.bad_color)

    def clean_memory_now(self):
        buttons = [b for b in (getattr(self, "clean_ram_button", None),
                               getattr(self, "settings_clean_button", None)) if b is not None]
        for button in buttons:
            button.configure(state="disabled", text=tr("Cleaning..."))
        purge = bool(self.purge_standby_switch.get()) if hasattr(self, "purge_standby_switch") \
            else self.alert_settings.get("purge_standby", True)

        def work():
            # Asks for administrator permission (UAC) when this app is not already elevated.
            try:
                result = memory_cleaner.clean_memory_elevated(purge_standby=purge)
            except Exception as exc:
                result = tr("memory cleanup failed: {error}").format(error=exc)

            def finish():
                for button in buttons:
                    button.configure(state="normal")
                if getattr(self, "clean_ram_button", None):
                    self.clean_ram_button.configure(text=tr("Clean RAM"))
                if getattr(self, "settings_clean_button", None):
                    self.settings_clean_button.configure(text=tr("🧹  Clean RAM now"))
                self.show_alert_banner(tr("Clean RAM"), result)
                self.last_alert_label.configure(text_color=self.good_color)
                if hasattr(self, "settings_status_label"):
                    self.settings_status_label.configure(text=result, text_color=self.good_color)
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def change_language(self, choice):
        language = "ko" if choice == "한국어" else "en"
        if language == i18n.get_language():
            return
        i18n.set_language(language)
        # Static labels and buttons
        i18n.retranslate_widgets(self.root, language)
        if self.pairing_dialog and self.pairing_dialog.winfo_exists():
            i18n.retranslate_widgets(self.pairing_dialog, language)
        # Tab names (CTkTabview keys)
        for key in self.tab_keys:
            old, new = (key, tr(key)) if language == "ko" else (i18n.KO.get(key, key), key)
            try:
                if old != new:
                    self.tab_control.rename(old, new)
            except Exception:
                pass
        # Texts that contain live values
        self.refresh_insight_mode()
        intro = "Start Monitoring, then press Analyze now to get a summary of how the CPU, memory, and GPU are being used."
        current = self.insight_text.get("1.0", "end").strip()
        if current in (intro, i18n.KO[intro]):
            self._show_insight(tr(intro))
        if self.remote_client:
            self.remote_status_label.configure(
                text=tr("Connected: {name}").format(name=self.remote_device_name))
        self.language_selector.set(choice)
        self.tray.refresh()
        if self._history_canvas is not None:
            self.refresh_history()

    def send_test_notification(self):
        error = notify(tr("System Resource Monitor"), tr("Test notification - alerts are working."))
        if error:
            self.settings_status_label.configure(
                text=tr("Notification failed: {error}. Check Windows notification settings.").format(error=error),
                text_color=self.bad_color)
        else:
            self.settings_status_label.configure(
                text=tr("Test notification sent. If nothing appeared, turn on notifications for this app in Windows Settings > System > Notifications."),
                text_color=self.good_color)

    def _on_alert_sent(self, title, message, error, key, local):
        self.show_alert_banner(title, message, error)
        if key == "memory" and local:
            self.auto_clean_memory()

    def auto_clean_memory(self):
        """RAM cleanup started by a memory alert (asks for administrator permission if needed)."""
        if self._auto_cleaning:
            return
        self._auto_cleaning = True
        purge = self.alert_settings.get("purge_standby", True)

        def work():
            try:
                result = memory_cleaner.clean_memory_elevated(purge_standby=purge)
            except Exception as exc:
                result = tr("memory cleanup failed: {error}").format(error=exc)
            notify(tr("Clean RAM"), result)

            def finish():
                self._auto_cleaning = False
                self.show_alert_banner(tr("Clean RAM"), result)
                self.last_alert_label.configure(text_color=self.good_color)
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def show_alert_banner(self, title, message, error=None):
        text = f"⚠ {time.strftime('%H:%M:%S')}  {title}: {message}"
        if error:
            text += "  (" + tr("notification failed: {error}").format(error=error) + ")"
        self.last_alert_label.configure(text=text, text_color=self.bad_color)
        if not self.last_alert_label.winfo_ismapped():
            self.last_alert_label.pack(anchor="w", padx=20, pady=(0, 8), after=self.control_header)

    # ---------------- AI insights ----------------

    def refresh_insight_mode(self):
        active = ai_insights.active_ai()
        if active:
            _, name, model = active
            self.insight_mode_label.configure(text=tr("{name} ({model})").format(name=name, model=model))
        else:
            self.insight_mode_label.configure(text=tr("Built-in analysis - add an API key for AI"))

    def _show_insight(self, text):
        self.insight_text.configure(state="normal")
        self.insight_text.delete("1.0", "end")
        self.insight_text.insert("1.0", text)
        self.insight_text.configure(state="disabled")

    def run_ai_insights(self):
        if self._insight_busy:
            return
        snapshot = ai_insights.build_snapshot(self)
        if not snapshot["cpu"] or not ai_insights.active_ai():
            self._show_insight(ai_insights.local_summary(snapshot))
            return
        self._insight_busy = True
        self.insight_button.configure(state="disabled", text=tr("Analyzing..."))

        def work():
            try:
                text = ai_insights.summarize(snapshot)
            except Exception as exc:
                text = (ai_insights.local_summary(snapshot) +
                        tr("\n\n(AI analysis failed: {error}. Showing built-in analysis.)").format(error=exc))

            def finish():
                self._insight_busy = False
                self.insight_button.configure(state="normal", text=tr("Analyze now"))
                self._show_insight(text)
            self.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def toggle_auto_insights(self):
        if self._auto_insight_job is not None:
            self.root.after_cancel(self._auto_insight_job)
            self._auto_insight_job = None
        if self.insight_auto_switch.get():
            self._auto_insight_tick()

    def _auto_insight_tick(self):
        if self.monitoring:
            self.run_ai_insights()
        self._auto_insight_job = self.root.after(60_000, self._auto_insight_tick)

    def configure_ai_key(self):
        """Dialog to save a Claude (Anthropic) or Gemini (Google) API key and pick which one to use."""
        if getattr(self, "ai_key_dialog", None) and self.ai_key_dialog.winfo_exists():
            self.ai_key_dialog.focus_force()
            return
        dark = self.theme_mode == "dark"
        text_color = "#c0caf5" if dark else "#202b3c"
        dim_color = "#a9b2d0" if dark else "#475569"
        dialog = ctk.CTkToplevel(self.root)
        self.ai_key_dialog = dialog
        dialog.title(tr("AI API keys"))
        dialog.geometry("520x330")
        dialog.resizable(False, False)
        dialog.configure(fg_color="#0f1117" if dark else "#f5f7fb")
        dialog.transient(self.root)

        choices = {"Claude (Anthropic)": "anthropic", "Gemini (Google)": "gemini"}
        hints = {
            "anthropic": tr("Anthropic key (starts with sk-ant-). Get one at console.anthropic.com."),
            "gemini": tr("Gemini key from Google AI Studio (aistudio.google.com)."),
        }
        ctk.CTkLabel(dialog, text=tr("Which AI writes the analysis?"), text_color=text_color,
                     font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")).pack(
            anchor="w", padx=20, pady=(18, 6))
        selector = ctk.CTkSegmentedButton(dialog, values=list(choices))
        selector.pack(anchor="w", padx=20)
        hint_label = ctk.CTkLabel(dialog, text="", text_color=dim_color, wraplength=480, justify="left")
        hint_label.pack(anchor="w", padx=20, pady=(12, 4))
        entry = ctk.CTkEntry(dialog, width=480, height=34, show="•",
                             placeholder_text=tr("Paste the API key here"))
        entry.pack(anchor="w", padx=20)
        saved_label = ctk.CTkLabel(dialog, text="", text_color=dim_color)
        saved_label.pack(anchor="w", padx=20, pady=(6, 0))

        def provider():
            return choices.get(selector.get(), "anthropic")

        def show_provider(_choice=None):
            key = ai_insights.get_api_key(provider())
            hint_label.configure(text=hints[provider()])
            saved_label.configure(
                text=tr("Saved key: ••••{last4}").format(last4=key[-4:]) if key else tr("No key saved"),
                text_color=self.good_color if key else dim_color)
            entry.delete(0, "end")

        def save():
            key = entry.get().strip()
            try:
                if key:
                    ai_insights.set_api_key(provider(), key)
                if ai_insights.get_api_key(provider()):
                    ai_insights.set_provider(provider())
                else:
                    saved_label.configure(text=tr("Enter a key first."), text_color=self.bad_color)
                    return
            except OSError as exc:
                messagebox.showerror(tr("Could not save key"), str(exc), parent=dialog)
                return
            self.refresh_insight_mode()
            dialog.destroy()

        def remove():
            try:
                ai_insights.set_api_key(provider(), "")
            except OSError as exc:
                messagebox.showerror(tr("Could not save key"), str(exc), parent=dialog)
                return
            show_provider()
            self.refresh_insight_mode()

        selector.configure(command=show_provider)
        current = ai_insights.get_provider()
        selector.set(next(name for name, value in choices.items() if value == current))
        show_provider()

        footer = ctk.CTkFrame(dialog, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=20, pady=16)
        ctk.CTkButton(footer, text=tr("Save and use"), width=130, command=save).pack(side="left")
        ctk.CTkButton(footer, text=tr("Remove key"), width=110, command=remove,
                      fg_color="#565f89" if dark else "#667085").pack(side="left", padx=8)
        ctk.CTkButton(footer, text=tr("Close"), width=90, command=dialog.destroy,
                      fg_color="#565f89" if dark else "#667085").pack(side="right")
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.after(100, entry.focus_set)

    def monitor_top_processes(self):
        """Top 20 processes by CPU. Paused while the window is hidden or a remote device is shown."""
        cpu_count = max(1, psutil.cpu_count() or 1)
        while self.monitoring:
            try:
                if getattr(self, "remote_client", None) or not self._window_visible:
                    time.sleep(2)
                    continue
                rows = []
                for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                    info = proc.info
                    cpu = info.get('cpu_percent')
                    if cpu is None:
                        continue
                    rows.append({'pid': info['pid'], 'name': info.get('name') or 'Unknown',
                                 'cpu_percent_normalized': cpu / cpu_count,
                                 'memory_percent': info.get('memory_percent') or 0.0})
                self._publish_processes(heapq.nlargest(20, rows, key=lambda p: p['cpu_percent_normalized']))
                del rows
            except Exception:
                pass
            time.sleep(2)

    def export_data(self):
        """Export the last 24 hours from the SQLite history (falls back to the in-memory samples)."""
        if not self.history:
            export_data(self)
            return
        from tkinter import filedialog
        import csv
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
                                            title=tr("Save monitoring data"))
        if not path:
            return
        self.history.flush()
        device = (self.remote_device_name or "Remote device") if self.remote_client else LOCAL_DEVICE
        since = time.time() - 86400
        rows = self.history.series(device, since, max_points=86400)
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Time", "CPU (%)", "Memory (%)", "GPU (%)", "GPU Memory (%)"])
            for ts, cpu, mem, gpu, gpu_mem in rows:
                fmt = lambda v: "" if v is None else f"{v:.1f}"
                writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                                 fmt(cpu), fmt(mem), fmt(gpu), fmt(gpu_mem)])

    def cleanup(self):
        self.monitoring = False
        self.tray.stop()
        if self.history:
            try:
                self.history.close()
            except Exception:
                pass
            self.history = None
        if self.pairing_server:
            self.pairing_server.stop()
        if self.remote_client:
            self.remote_client.close()
            self.remote_client = None
        self.root.quit()
