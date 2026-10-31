"""System tray icon (pystray) and "start with Windows" (HKCU Run key)."""
import os
import sys

from .i18n import tr

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "SystemResourceMonitor"


# ---------------- start with Windows ----------------

def startup_command():
    """Command that starts the app minimized to the tray with monitoring on."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if os.path.exists(pythonw) else sys.executable
    main_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{interpreter}" "{main_script}" --minimized'


def is_autostart_enabled():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
        return True
    except OSError:
        return False


def set_autostart(enabled):
    """Add or remove the Run entry for the current user (no admin rights needed)."""
    if sys.platform != "win32":
        raise OSError("Start with Windows is only available on Windows")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


# ---------------- tray icon ----------------

def _icon_image():
    from PIL import Image, ImageDraw
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, size - 2, size - 2), radius=14, fill=(26, 27, 38, 255))
    bars = [(12, 38), (24, 22), (36, 30), (48, 14)]
    for x, top in bars:
        draw.rounded_rectangle((x, top, x + 8, 52), radius=3, fill=(122, 162, 247, 255))
    return image


class TrayIcon:
    """Tray icon with Open / Start-Stop monitoring / Quit. Callbacks run on the Tk thread."""

    def __init__(self, app):
        self.app = app
        self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def start(self):
        try:
            import pystray
        except Exception:
            return False  # pystray / Pillow not installed: closing the window quits instead

        def on_tk(callback):
            return lambda _icon=None, _item=None: self.app.root.after(0, callback)

        menu = pystray.Menu(
            pystray.MenuItem(lambda _item: tr("Open"), on_tk(self.app.show_window), default=True),
            pystray.MenuItem(
                lambda _item: tr("Stop monitoring") if self.app.monitoring else tr("Start monitoring"),
                on_tk(self.app.toggle_monitoring_from_tray)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _item: tr("Quit"), on_tk(self.app.quit_app)),
        )
        try:
            self.icon = pystray.Icon("SystemResourceMonitor", _icon_image(),
                                     tr("System Resource Monitor"), menu)
            self.icon.run_detached()
        except Exception:
            self.icon = None
            return False
        return True

    def notify(self, title, message):
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
            except Exception:
                pass

    def refresh(self):
        if self.icon is not None:
            try:
                self.icon.title = tr("System Resource Monitor")
                self.icon.update_menu()
            except Exception:
                pass

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
