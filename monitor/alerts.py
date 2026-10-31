"""User-configurable usage alerts (Windows notifications).

Settings are stored next to the AI key in %APPDATA%\\SystemResourceMonitor\\config.json.
"""
import time

from .i18n import tr

from .ai_insights import load_config, save_config

DEFAULTS = {
    "alerts_enabled": True,
    "cpu": 85.0,
    "memory": 90.0,
    "gpu": 95.0,
    "gpu_memory": 90.0,
    "duration_seconds": 30,     # value must stay above the limit this long
    "cooldown_minutes": 5,      # minimum gap between repeated alerts of the same kind
    "interval_seconds": 1.0,    # monitoring update interval
    "purge_standby": True,      # RAM cleanup also purges the standby list (Mem Reduct style)
    "minimize_to_tray": True,   # closing the window keeps the app running in the tray
    "history_days": 30,         # how long usage history is kept
}

LABELS = {"cpu": "CPU", "memory": "Memory", "gpu": "GPU", "gpu_memory": "GPU Memory"}


def load_settings():
    settings = dict(DEFAULTS)
    stored = load_config().get("alerts", {})
    for key, default in DEFAULTS.items():
        if key in stored:
            try:
                settings[key] = type(default)(stored[key])
            except (TypeError, ValueError):
                pass
    return settings


def save_settings(settings):
    config = load_config()
    config["alerts"] = {key: settings[key] for key in DEFAULTS}
    save_config(config)


def notify(title, message):
    """Show a Windows toast. Returns an error string, or None on success."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message,
                            app_name="System Resource Monitor", timeout=8)
        return None
    except Exception as exc:  # plyer backend missing, notifications disabled, ...
        return str(exc) or exc.__class__.__name__


class AlertTracker:
    """Fires one notification when a metric stays above its limit for long enough."""

    def __init__(self):
        self.above_since = {}
        self.last_sent = {}

    def reset(self):
        self.above_since.clear()

    def check(self, settings, values, device_name, on_sent=None, notes=None):
        """notes: extra text appended to a metric's alert message, e.g. {"memory": " Cleaning up RAM now."}"""
        if not settings.get("alerts_enabled"):
            self.above_since.clear()
            return
        now = time.time()
        for key, value in values.items():
            limit = settings.get(key)
            if value is None or limit is None or value <= 0 or value < limit:
                self.above_since.pop(key, None)
                continue
            started = self.above_since.setdefault(key, now)
            if now - started < settings["duration_seconds"]:
                continue
            if now - self.last_sent.get(key, 0) < settings["cooldown_minutes"] * 60:
                continue
            self.last_sent[key] = now
            self.above_since.pop(key, None)
            label = tr(LABELS.get(key, key))
            title = tr("{label} usage alert — {device}").format(label=label, device=device_name)
            message = tr("{label} is at {value}% (limit {limit}%), above the limit for {seconds}s.").format(
                label=label, value=f"{value:.1f}", limit=f"{limit:.0f}", seconds=int(now - started))
            if notes and notes.get(key):
                message += notes[key]
            error = notify(title, message)
            if on_sent:
                on_sent(title, message, error, key)
