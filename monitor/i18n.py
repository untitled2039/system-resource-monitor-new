"""Korean / English UI text.

English strings are the keys. tr() returns the Korean text when Korean is selected.
Templates with {placeholders} are translated first, then formatted by the caller:
    tr("Connected: {name}").format(name=device)
"""
import json
import os

KO = {
    # Window / tabs / top bar
    "System Resource Monitor": "시스템 리소스 모니터",
    "📊 Resource Monitor": "📊 리소스 모니터",
    "🔧 Top Processes": "🔧 상위 프로세스",
    "⚙ Settings": "⚙ 설정",
    "Light": "라이트",
    "Dark": "다크",
    "Fullscreen": "전체화면",
    "Windowed": "창 모드",

    # Resource monitor tab
    "Current Resource Usage": "현재 리소스 사용량",
    "CPU": "CPU",
    "Memory": "메모리",
    "GPU": "GPU",
    "GPU Memory": "GPU 메모리",
    "AI Insights": "AI 분석",
    "API key": "API 키",
    "Auto (60s)": "자동 (60초)",
    "Analyze now": "지금 분석",
    "Analyzing...": "분석 중...",
    "Start Monitoring, then press Analyze now to get a summary of how the CPU, memory, and GPU are being used.":
        "모니터링을 시작한 뒤 '지금 분석'을 누르면 CPU, 메모리, GPU 사용 상태를 요약해 드립니다.",
    "Built-in analysis - add an API key for AI": "기본 분석 - AI를 쓰려면 API 키를 추가하세요",
    "{name} ({model})": "{name} ({model})",
    "AI API keys": "AI API 키",
    "Which AI writes the analysis?": "어떤 AI로 분석할까요?",
    "Anthropic key (starts with sk-ant-). Get one at console.anthropic.com.":
        "Anthropic 키(sk-ant-로 시작)를 넣으세요. console.anthropic.com에서 발급받을 수 있습니다.",
    "Gemini key from Google AI Studio (aistudio.google.com).":
        "Google AI Studio(aistudio.google.com)에서 발급받은 Gemini 키를 넣으세요.",
    "Paste the API key here": "여기에 API 키를 붙여 넣으세요",
    "Saved key: ••••{last4}": "저장된 키: ••••{last4}",
    "No key saved": "저장된 키 없음",
    "Enter a key first.": "먼저 키를 입력하세요.",
    "Save and use": "저장하고 사용",
    "Remove key": "키 삭제",
    "Close": "닫기",
    "\n\n(AI analysis failed: {error}. Showing built-in analysis.)":
        "\n\n(AI 분석 실패: {error}. 기본 분석 결과를 표시합니다.)",
    "Anthropic API key": "Anthropic API 키",
    "Paste an Anthropic API key (sk-ant-...) to let Claude write the analysis.\nLeave it empty and press Ok to remove the saved key.":
        "Claude가 분석을 작성하도록 Anthropic API 키(sk-ant-...)를 붙여 넣으세요.\n비워 두고 Ok를 누르면 저장된 키가 삭제됩니다.",
    "Could not save key": "키를 저장하지 못했습니다",
    "Control Panel": "제어판",
    "● Monitoring Stopped": "● 모니터링 중지됨",
    "● Monitoring Active": "● 모니터링 중",
    "🟢 Monitoring Active": "🟢 모니터링 중",
    "🔴 Monitoring Stopped": "🔴 모니터링 중지됨",
    "▶  Start Monitoring": "▶  모니터링 시작",
    "⏹  Stop Monitoring": "⏹  모니터링 중지",
    "💾  Export Data": "💾  데이터 내보내기",
    "Remote devices (Wi-Fi / LAN)": "원격 기기 (Wi-Fi / LAN)",
    "Not connected": "연결 안 됨",
    "Connect device": "기기 연결",
    "Disconnect": "연결 끊기",
    "Connected: {name}": "연결됨: {name}",
    "Disconnected; monitoring local device": "연결이 끊겨 이 PC를 모니터링합니다",
    " (CPU: clock-speed estimate)": " (CPU: 클럭 기반 추정치)",
    " (CPU unavailable)": " (CPU 측정 불가)",
    "this PC": "이 PC",

    # Pairing dialog
    "Connect a device": "기기 연결하기",
    "Enter this code on your device": "기기에서 이 코드를 입력하세요",
    "Android app or Raspberry Pi agent, on the same Wi-Fi / LAN":
        "같은 Wi-Fi / LAN에 있는 Android 앱 또는 라즈베리파이 에이전트",
    "Starting...": "시작하는 중...",
    "This PC: {addresses}  (port {port})": "이 PC: {addresses}  (포트 {port})",
    "New code": "새 코드",
    "Cancel": "취소",
    "Waiting for a device to connect...": "기기 연결을 기다리는 중...",
    "A device entered a wrong code ({count}/5). After 5 wrong attempts a new code is generated.":
        "기기에서 잘못된 코드를 입력했습니다 ({count}/5). 5번 틀리면 새 코드가 만들어집니다.",

    # Processes tab
    "Top 20 Processes by CPU Usage": "CPU 사용량 상위 20개 프로세스",
    "Top 20 Processes — {name}": "상위 20개 프로세스 — {name}",
    "Top Processes (Android app only)": "상위 프로세스 (Android 앱만)",
    "Recently Used Apps (Android)": "최근 사용한 앱 (Android)",
    "Top 20 Processes (Android, via Shizuku)": "상위 20개 프로세스 (Android, Shizuku)",
    "💾  Export Processes": "💾  프로세스 내보내기",
    "PID": "PID",
    "Process Name": "프로세스 이름",
    "CPU Usage": "CPU 사용량",
    "Export Failed": "내보내기 실패",
    "No processes to export.": "내보낼 프로세스가 없습니다.",
    "Export Successful": "내보내기 완료",
    "Processes exported to 'top_processes.txt'": "프로세스 목록을 'top_processes.txt'로 내보냈습니다",
    "An error occurred while exporting: {error}": "내보내는 중 오류가 발생했습니다: {error}",
    "Error": "오류",
    "Error monitoring processes: {error}": "프로세스를 확인하는 중 오류가 발생했습니다: {error}",

    # Settings tab
    "Language": "언어",
    "Usage alerts": "사용량 알림",
    "The PC shows a Windows notification when a value stays at or above its limit. This also applies to a connected Android / Raspberry Pi device.":
        "값이 한도 이상으로 유지되면 PC에 Windows 알림을 보냅니다. 연결된 Android / 라즈베리파이 기기에도 적용됩니다.",
    "Send notifications": "알림 보내기",
    "CPU limit (%)": "CPU 한도 (%)",
    "Memory limit (%)": "메모리 한도 (%)",
    "GPU limit (%)": "GPU 한도 (%)",
    "GPU memory limit (%)": "GPU 메모리 한도 (%)",
    "Alert after (s)": "알림 대기 시간 (초)",
    "Repeat after (min)": "재알림 간격 (분)",
    "Update interval (s)": "측정 주기 (초)",
    "Alert at or above": "이 값 이상이면 알림",
    "Ignored if GPU reads 0": "GPU 값이 0이면 무시",
    "Ignored if it reads 0": "값이 0이면 무시",
    "Time above the limit": "한도를 넘은 채 유지된 시간",
    "Gap between alerts": "같은 알림 사이 간격",
    "How often to measure": "측정 간격",
    "Save settings": "설정 저장",
    "Send test notification": "테스트 알림 보내기",
    "Enter a number for every field ({field}).": "모든 칸에 숫자를 입력하세요 ({field}).",
    "{field}: use a value between {low} and {high}.": "{field}: {low}에서 {high} 사이 값을 입력하세요.",
    "Saved.": "저장했습니다.",
    "Applied, but could not save to disk: {error}": "적용했지만 파일에 저장하지 못했습니다: {error}",
    "Notification failed: {error}. Check Windows notification settings.":
        "알림을 보내지 못했습니다: {error}. Windows 알림 설정을 확인하세요.",
    "Test notification sent. If nothing appeared, turn on notifications for this app in Windows Settings > System > Notifications.":
        "테스트 알림을 보냈습니다. 알림이 보이지 않으면 Windows 설정 > 시스템 > 알림에서 이 앱의 알림을 켜 주세요.",
    "Test notification - alerts are working.": "테스트 알림 - 알림이 정상적으로 동작합니다.",
    "RAM cleanup": "RAM 정리 기능",
    " Cleaning up RAM now.": " 지금 RAM을 정리합니다.",
    "; silent cleanup could not be set up: {error}": "; 확인 창 없는 자동 정리를 설정하지 못했습니다: {error}",
    "Memory cleanup also purges the standby list (frees the most RAM; apps may reload files from disk once)":
        "대기(standby) 목록도 비우기 (가장 많은 RAM 확보, 앱이 파일을 디스크에서 한 번 다시 읽을 수 있음)",
    "🧹  Clean RAM now": "🧹  지금 RAM 정리",
    "Cleaning...": "정리 중...",
    "Clean RAM": "RAM 정리",

    # Alerts (Windows notifications)
    "{label} usage alert — {device}": "{label} 사용량 알림 — {device}",
    "{label} is at {value}% (limit {limit}%), above the limit for {seconds}s.":
        "{label} 사용률이 {value}%입니다 (한도 {limit}%). {seconds}초 동안 한도를 넘었습니다.",
    "notification failed: {error}": "알림 전송 실패: {error}",

    # RAM cleanup results
    "memory cleanup is only available on Windows": "RAM 정리는 Windows에서만 사용할 수 있습니다",
    "RAM {before}% -> {after}% (freed {freed} MB)": "RAM {before}% -> {after}% ({freed} MB 확보)",
    "; skipped: {steps}": "; 건너뜀: {steps}",
    "system memory lists (administrator permission needed)": "시스템 메모리 목록 (관리자 권한 필요)",
    "cancelled: administrator permission was not granted": "취소됨: 관리자 권한이 허용되지 않았습니다",
    "could not start the cleanup (error {code})": "정리를 시작하지 못했습니다 (오류 {code})",
    "the cleanup finished without a result (it may have timed out)": "정리가 결과 없이 끝났습니다 (시간 초과일 수 있음)",
    "memory cleanup failed: {error}": "RAM 정리 실패: {error}",
    "working sets": "작업 집합",
    "file cache": "파일 캐시",
    "modified list": "수정된 페이지 목록",
    "low-priority standby": "낮은 우선순위 대기 목록",
    "standby list": "대기 목록",
    "page combining": "페이지 병합",
    "working sets of {count} apps": "앱 {count}개의 작업 집합",
    # History tab
    "📈 History": "📈 기록",
    "Usage history": "사용량 기록",
    "Refresh": "새로고침",
    "Analyze this period": "이 기간 분석",
    "Press Analyze this period for an explanation of this period.": "'이 기간 분석'을 누르면 선택한 기간의 사용 패턴을 설명해 드립니다.",
    "No history in this period yet.": "이 기간에는 아직 기록이 없습니다.",
    "History is unavailable: {error}": "기록을 사용할 수 없습니다: {error}",
    "CPU avg {cpu}% · peak {cpu_peak}%    Memory avg {mem}% · peak {mem_peak}%":
        "CPU 평균 {cpu}% · 최고 {cpu_peak}%    메모리 평균 {mem}% · 최고 {mem_peak}%",
    "GPU avg {gpu}% · peak {gpu_peak}%": "GPU 평균 {gpu}% · 최고 {gpu_peak}%",
    "No data": "데이터 없음",
    "Keep history (days)": "기록 보관 기간 (일)",
    "Older records are deleted": "지난 기록은 자동 삭제",

    # Tray / startup
    "Open": "열기",
    "Start monitoring": "모니터링 시작",
    "Stop monitoring": "모니터링 중지",
    "Quit": "종료",
    "Keep running in the tray when the window is closed": "창을 닫아도 트레이에서 계속 실행",
    "Start with Windows (in the tray, monitoring on)": "Windows 시작 시 자동 실행 (트레이에서 모니터링)",
    "Still running in the tray. Right-click the tray icon to quit.":
        "트레이에서 계속 실행 중입니다. 종료하려면 트레이 아이콘을 오른쪽 클릭하세요.",
    "Could not change Windows startup: {error}": "Windows 시작 프로그램 설정을 바꾸지 못했습니다: {error}",
}

REVERSE = {korean: english for english, korean in KO.items()}

LANGUAGES = {"en": "English", "ko": "한국어"}
_language = None


def _config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SystemResourceMonitor", "config.json")


def _system_language():
    try:
        import ctypes
        if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x12:  # LANG_KOREAN
            return "ko"
    except Exception:
        pass
    try:
        import locale
        if (locale.getlocale()[0] or "").lower().startswith(("ko", "korean")):
            return "ko"
    except Exception:
        pass
    return "en"


def get_language():
    global _language
    if _language is None:
        try:
            with open(_config_path(), "r", encoding="utf-8") as handle:
                _language = json.load(handle).get("language")
        except (OSError, ValueError):
            _language = None
        if _language not in LANGUAGES:
            _language = _system_language()
    return _language


def set_language(language):
    """Switch language and remember it in the config file."""
    global _language
    _language = language if language in LANGUAGES else "en"
    path = _config_path()
    try:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, ValueError):
            config = {}
        config["language"] = _language
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
    except OSError:
        pass


def tr(text):
    if get_language() == "ko":
        return KO.get(text, text)
    return text


def retranslate_widgets(widget, language):
    """Swap the text of every widget whose text is a known static string."""
    table = KO if language == "ko" else REVERSE
    try:
        current = widget.cget("text")
    except Exception:
        current = None
    if isinstance(current, str) and current in table:
        try:
            widget.configure(text=table[current])
        except Exception:
            pass
    for child in widget.winfo_children():
        retranslate_widgets(child, language)
