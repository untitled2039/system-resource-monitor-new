"""Plain-language summary of recent resource usage.

With a Claude (Anthropic) or Gemini (Google) API key the summary is written by AI; without one a
built-in rule-based summary is shown so the panel is still useful offline.
"""
import json
import os
import statistics
import time
import urllib.error
import urllib.request

from . import secure_store
from .i18n import get_language, tr

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODEL = "gemini-3.8-flash"


def _config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SystemResourceMonitor", "config.json")


def load_config():
    try:
        with open(_config_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def save_config(config):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


PROVIDERS = {
    # provider: (display name, config key, environment variable, default model)
    "anthropic": ("Claude", "anthropic_api_key", "ANTHROPIC_API_KEY", DEFAULT_MODEL),
    "gemini": ("Gemini", "gemini_api_key", "GEMINI_API_KEY", GEMINI_MODEL),
}


def get_api_key(provider):
    """Saved key (decrypted), or the provider's environment variable."""
    _, config_key, env_var, _ = PROVIDERS[provider]
    config = load_config()
    token = config.get(config_key + "_dpapi")
    if token:
        try:
            return secure_store.unprotect(token)
        except (OSError, ValueError):
            return ""  # saved under another Windows account or corrupted
    plain = config.get(config_key)
    if plain and secure_store.available():
        # Migrate a key saved by an older version (plain text) to encrypted storage.
        try:
            set_api_key(provider, plain)
        except OSError:
            pass
    return plain or os.environ.get(env_var) or ""


def set_api_key(provider, key):
    """Save (encrypted with Windows DPAPI) or remove a key."""
    config = load_config()
    config_key = PROVIDERS[provider][1]
    config.pop(config_key, None)
    config.pop(config_key + "_dpapi", None)
    if key:
        if secure_store.available():
            config[config_key + "_dpapi"] = secure_store.protect(key)
        else:
            config[config_key] = key
    save_config(config)


def get_provider():
    """Selected provider; falls back to whichever provider has a key."""
    selected = load_config().get("ai_provider", "anthropic")
    if selected not in PROVIDERS:
        selected = "anthropic"
    if get_api_key(selected):
        return selected
    for provider in PROVIDERS:
        if get_api_key(provider):
            return provider
    return selected


def set_provider(provider):
    config = load_config()
    config["ai_provider"] = provider
    save_config(config)


def active_ai():
    """(provider, display name, model) when an AI key is available, else None."""
    provider = get_provider()
    if not get_api_key(provider):
        return None
    name, _, _, model = PROVIDERS[provider]
    return provider, name, model


def summarize(snapshot, kind="live"):
    """AI summary with the active provider. Raises RuntimeError on failure or if no key is set.

    kind="live" explains the last minute; kind="period" explains a stored history period.
    """
    active = active_ai()
    if active is None:
        raise RuntimeError("no API key")
    provider = active[0]
    key = get_api_key(provider)
    if provider == "gemini":
        return gemini_summary(snapshot, key, system=_system_prompt(kind))
    return claude_summary(snapshot, key, system=_system_prompt(kind))


def build_period_snapshot(store, device, device_label, since, range_label):
    """Statistics for a history period (hourly rows up to 2 days, daily rows beyond)."""
    span = time.time() - since
    period = 3600 if span <= 2 * 86400 else 86400
    stats = store.stats(device, since)
    if not stats:
        return None
    rnd = lambda value: None if value is None else round(value, 1)
    return {
        "device": device_label,
        "range": range_label,
        "from": time.strftime("%Y-%m-%d %H:%M", time.localtime(stats["first"])),
        "to": time.strftime("%Y-%m-%d %H:%M", time.localtime(stats["last"])),
        "overall": {metric: {k: rnd(v) for k, v in values.items()}
                    for metric, values in stats.items() if isinstance(values, dict)},
        "thresholds_note": "values are percentages",
        ("hourly" if period == 3600 else "daily"): store.periods(device, since, period),
    }


def local_period_summary(data):
    """Rule-based summary of a history period (used without an API key)."""
    if not data:
        return _t("이 기간에 저장된 기록이 없습니다.", "No history was recorded in this period.")
    overall = data["overall"]
    rows = data.get("hourly") or data.get("daily") or []
    lines = [_t(f"{data['device']} · {data['from']} ~ {data['to']}",
                f"{data['device']} · {data['from']} to {data['to']}")]
    cpu, mem = overall["cpu"], overall["memory"]
    lines.append(_t(f"CPU 평균 {cpu['avg']}%, 최고 {cpu['max']}% / 메모리 평균 {mem['avg']}%, 최고 {mem['max']}%",
                    f"CPU avg {cpu['avg']}%, peak {cpu['max']}% / Memory avg {mem['avg']}%, peak {mem['max']}%"))
    gpu = overall.get("gpu") or {}
    if gpu.get("max"):
        lines.append(_t(f"GPU 평균 {gpu['avg']}%, 최고 {gpu['max']}%", f"GPU avg {gpu['avg']}%, peak {gpu['max']}%"))
    busy = [row for row in rows if row.get("cpu_avg") is not None]
    if len(busy) > 1:
        top = max(busy, key=lambda row: row["cpu_avg"])
        top_mem = max(busy, key=lambda row: row["memory_avg"] or 0)
        lines.append(_t(f"CPU가 가장 바빴던 시간: {top['start']} (평균 {top['cpu_avg']}%)",
                        f"Busiest CPU period: {top['start']} (avg {top['cpu_avg']}%)"))
        lines.append(_t(f"메모리를 가장 많이 쓴 시간: {top_mem['start']} (평균 {top_mem['memory_avg']}%)",
                        f"Highest memory period: {top_mem['start']} (avg {top_mem['memory_avg']}%)"))
    return "\n".join(lines)


def _series_stats(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return None
    return {
        "now": round(values[-1], 1),
        "avg": round(statistics.fmean(values), 1),
        "max": round(max(values), 1),
        "min": round(min(values), 1),
        "trend": round(values[-1] - values[0], 1) if len(values) > 1 else 0.0,
    }


def build_snapshot(monitor):
    """Collect the last ~60 samples and the current top processes from the monitor."""
    processes = []
    for proc in (getattr(monitor, "latest_processes", None) or [])[:8]:
        processes.append({
            "name": str(proc.get("name")),
            "cpu_percent": None if proc.get("cpu_percent_normalized") is None
            else round(float(proc["cpu_percent_normalized"]), 1),
            "memory_percent": None if proc.get("memory_percent") is None
            else round(float(proc["memory_percent"]), 1),
        })
    return {
        "device": getattr(monitor, "remote_device_name", None) or tr("this PC"),
        "seconds_covered": len(monitor.cpu_history) * max(1, int(monitor.CPU_MON_INTERVAL)),
        "cpu": _series_stats(monitor.cpu_history),
        "memory": _series_stats(monitor.memory_history),
        "gpu": _series_stats(monitor.gpu_history),
        "gpu_memory": _series_stats(monitor.gpu_memory_history),
        "thresholds": {"cpu": monitor.CPU_THRESHOLD, "memory": monitor.MEMORY_THRESHOLD,
                       "gpu": monitor.GPU_THRESHOLD},
        "top_processes": processes,
    }


def _t(korean, english):
    return korean if get_language() == "ko" else english


def _level(value, threshold):
    if value >= threshold:
        return _t("매우 높음", "very high")
    if value >= threshold * 0.7:
        return _t("높은 편", "high")
    if value >= threshold * 0.35:
        return _t("보통", "moderate")
    return _t("여유", "light")


def local_summary(snapshot):
    """Rule-based Korean summary used when no API key is set or the API fails."""
    if not snapshot["cpu"]:
        return _t("아직 측정값이 없습니다. 모니터링을 시작하면 상태를 분석합니다.",
                  "No readings yet. Start Monitoring and the status will be analyzed.")
    lines = []
    cpu, mem = snapshot["cpu"], snapshot["memory"]
    th = snapshot["thresholds"]
    lines.append(_t(f"{snapshot['device']} · 최근 {snapshot['seconds_covered']}초 기준",
                    f"{snapshot['device']} · last {snapshot['seconds_covered']}s"))
    lines.append(_t(f"CPU {cpu['now']}% (평균 {cpu['avg']}%, 최고 {cpu['max']}%) — {_level(cpu['avg'], th['cpu'])}",
                    f"CPU {cpu['now']}% (avg {cpu['avg']}%, peak {cpu['max']}%) — {_level(cpu['avg'], th['cpu'])}"))
    lines.append(_t(f"메모리 {mem['now']}% (평균 {mem['avg']}%) — {_level(mem['avg'], th['memory'])}",
                    f"Memory {mem['now']}% (avg {mem['avg']}%) — {_level(mem['avg'], th['memory'])}"))
    gpu = snapshot["gpu"]
    if gpu and gpu["max"] > 0:
        lines.append(_t(f"GPU {gpu['now']}% (평균 {gpu['avg']}%, 최고 {gpu['max']}%)",
                        f"GPU {gpu['now']}% (avg {gpu['avg']}%, peak {gpu['max']}%)"))
    tips = []
    if cpu["avg"] >= th["cpu"]:
        tips.append(_t("CPU가 계속 한도를 넘고 있습니다. 상위 프로세스를 확인해 보세요.",
                       "CPU keeps exceeding its limit. Check the top processes."))
    elif cpu["trend"] >= 20:
        tips.append(_t("CPU 사용률이 빠르게 오르고 있습니다.", "CPU usage is rising quickly."))
    if mem["avg"] >= th["memory"]:
        tips.append(_t("메모리가 부족합니다. 사용하지 않는 프로그램을 닫거나 RAM 정리를 해 보세요.",
                       "Memory is running low. Close unused programs or run a RAM cleanup."))
    elif mem["trend"] >= 10:
        tips.append(_t("메모리 사용량이 계속 늘고 있습니다(누수 가능성).",
                       "Memory usage keeps growing (possible leak)."))
    top = [p for p in snapshot["top_processes"] if p["cpu_percent"]]
    if top:
        tips.append(_t("CPU를 가장 많이 쓰는 프로세스: ", "Top CPU users: ") + ", ".join(
            f"{p['name']} {p['cpu_percent']}%" for p in top[:3]))
    lines.append(" ".join(tips) if tips else _t("전반적으로 안정적인 상태입니다.", "Everything looks stable."))
    return "\n".join(lines)


def _system_prompt(kind="live"):
    if kind == "period":
        return (
            "You are a system-monitoring assistant inside a desktop resource monitor. "
            f"The JSON describes CPU, memory and GPU usage (percent) over a past period, with "
            f"overall averages/peaks and per-hour or per-day rows. In {_t('Korean', 'English')}, in 4-6 short "
            "sentences, describe the usage pattern: busiest times, unusual spikes, whether memory "
            "trends upward over time, and one or two concrete suggestions. Use plain text without "
            "markdown and only numbers that appear in the data."
        )
    return (
        "You are a system-monitoring assistant inside a desktop resource monitor. "
        f"Given JSON statistics for the last minute, explain in {_t('Korean', 'English')}, in 3-5 short "
        "sentences, how busy the device is, what stands out (spikes, trends, heavy "
        "processes), and one concrete suggestion if something needs attention. "
        "Use plain text without markdown. Do not invent numbers that are not in the data. "
        "GPU values of 0 may mean the device does not report GPU usage."
    )


def _post_json(url, body, headers, timeout):
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json", **headers},
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            message = None
        raise RuntimeError(f"API error {exc.code}: {message or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Network error: {exc}") from exc


def gemini_summary(snapshot, api_key, model=GEMINI_MODEL, timeout=30, system=None):
    """Ask Gemini for a short explanation. Raises RuntimeError on failure."""
    body = {
        "systemInstruction": {"parts": [{"text": system or _system_prompt()}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(snapshot, ensure_ascii=False)}]}],
        "generationConfig": {"maxOutputTokens": 1024},
    }
    data = _post_json(GEMINI_URL.format(model=model), body, {"x-goog-api-key": api_key}, timeout)
    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
    text = "".join(part.get("text", "") for part in parts if not part.get("thought")).strip()
    if not text:
        reason = candidates[0].get("finishReason") if candidates else \
            (data.get("promptFeedback") or {}).get("blockReason")
        raise RuntimeError(f"Gemini returned an empty answer ({reason or 'no candidates'}).")
    return text


def claude_summary(snapshot, api_key, model=DEFAULT_MODEL, timeout=30, system=None):
    """Ask Claude for a short Korean explanation. Raises RuntimeError on failure."""
    body = {
        "model": model,
        "max_tokens": 400,
        "system": system or _system_prompt(),
        "messages": [{"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)}],
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
        except Exception:
            message = None
        raise RuntimeError(f"API error {exc.code}: {message or exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Network error: {exc}") from exc
    text = "".join(block.get("text", "") for block in data.get("content", [])
                   if block.get("type") == "text").strip()
    if not text:
        raise RuntimeError("The API returned an empty answer.")
    return text
