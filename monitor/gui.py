import customtkinter as ctk
from tkinter import messagebox
from utils.utils import gather_system_info
from .i18n import tr, get_language
from .tray import is_autostart_enabled
import requests

# ---- 전역 테마 (바이브코딩 다크 스타일) ----
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# 색상 팔레트
BG        = "#0f1117"   # 가장 바깥 배경
CARD      = "#1a1b26"   # 카드(도시락칸) 배경
CARD_SOFT = "#20222e"   # 입력 필드 등 안쪽
ACCENT    = "#7aa2f7"   # 포인트
TEXT      = "#c0caf5"
TEXT_DIM  = "#565f89"
GOOD      = "#9ece6a"
BAD       = "#f7768e"

def build_history_tab(self, tab, font_title, font_label, font_bold):
    """Long-term usage graph from the SQLite history, with a period analysis by AI."""
    frame = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=16)
    frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    top = ctk.CTkFrame(frame, fg_color="transparent")
    top.pack(fill="x", padx=20, pady=(16, 6))
    ctk.CTkLabel(top, text=tr("Usage history"), font=font_title, text_color=TEXT).pack(side="left")
    self.history_range = ctk.CTkSegmentedButton(
        top, values=["1h", "6h", "24h", "7d", "30d"], command=lambda _value: self.refresh_history(),
        selected_color=ACCENT, selected_hover_color=ACCENT)
    self.history_range.set("24h")
    self.history_range.pack(side="left", padx=16)
    self.history_device_menu = ctk.CTkOptionMenu(
        top, values=[tr("this PC")], width=190, command=lambda _value: self.refresh_history())
    self.history_device_menu.pack(side="left")
    ctk.CTkButton(top, text=tr("Refresh"), width=90, command=self.refresh_history,
                  fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT).pack(side="right")

    self.history_stats_label = ctk.CTkLabel(frame, text="", font=font_label,
                                            text_color=TEXT_DIM, anchor="w", justify="left")
    self.history_stats_label.pack(fill="x", padx=20, pady=(0, 6))

    # AI row is packed at the bottom first so the chart takes the remaining space.
    ai_frame = ctk.CTkFrame(frame, fg_color="transparent")
    ai_frame.pack(side="bottom", fill="x", padx=20, pady=(6, 16))
    ai_header = ctk.CTkFrame(ai_frame, fg_color="transparent")
    ai_header.pack(fill="x")
    ctk.CTkLabel(ai_header, text=tr("AI Insights"), font=font_bold, text_color=TEXT).pack(side="left")
    self.history_ai_button = ctk.CTkButton(ai_header, text=tr("Analyze this period"), width=160,
                                           command=self.analyze_history_period)
    self.history_ai_button.pack(side="right")
    self.history_ai_text = ctk.CTkTextbox(
        ai_frame, height=90, corner_radius=12, fg_color=CARD_SOFT, text_color=TEXT,
        font=ctk.CTkFont(family="Malgun Gothic", size=13), wrap="word")
    self.history_ai_text.pack(fill="x", pady=(6, 0))
    self.history_ai_text.insert("1.0", tr("Press Analyze this period for an explanation of this period."))
    self.history_ai_text.configure(state="disabled")

    self.history_chart_frame = ctk.CTkFrame(frame, fg_color=CARD_SOFT, corner_radius=12)
    self.history_chart_frame.pack(fill="both", expand=True, padx=20)


def build_settings_tab(self, tab, font_title, font_label, font_bold):
    """Alert thresholds and monitoring options, saved to the user's config file."""
    # Plain frame (not CTkScrollableFrame) so the light/dark theme switch recolors it fully.
    frame = ctk.CTkFrame(tab, fg_color=CARD, corner_radius=16)
    frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    language_row = ctk.CTkFrame(frame, fg_color="transparent")
    language_row.pack(fill="x", padx=20, pady=(16, 0))
    ctk.CTkLabel(language_row, text="Language / 언어", font=font_bold,
                 text_color=TEXT).pack(side="left")
    self.language_selector = ctk.CTkSegmentedButton(
        language_row, values=["English", "한국어"], command=self.change_language,
        selected_color=ACCENT, selected_hover_color=ACCENT)
    self.language_selector.pack(side="left", padx=12)
    self.language_selector.set("한국어" if get_language() == "ko" else "English")

    background_row = ctk.CTkFrame(frame, fg_color="transparent")
    background_row.pack(fill="x", padx=20, pady=(10, 0))
    self.tray_switch = ctk.CTkSwitch(
        background_row, text=tr("Keep running in the tray when the window is closed"),
        font=font_label, text_color=TEXT, progress_color=ACCENT,
        command=self.save_background_options)
    self.tray_switch.pack(side="left")
    if self.alert_settings["minimize_to_tray"]:
        self.tray_switch.select()
    self.autostart_switch = ctk.CTkSwitch(
        background_row, text=tr("Start with Windows (in the tray, monitoring on)"),
        font=font_label, text_color=TEXT, progress_color=ACCENT,
        command=self.toggle_autostart)
    self.autostart_switch.pack(side="left", padx=24)
    if is_autostart_enabled():
        self.autostart_switch.select()

    ctk.CTkLabel(frame, text=tr("Usage alerts"), font=font_title,
                 text_color=TEXT).pack(anchor="w", padx=20, pady=(16, 2))
    ctk.CTkLabel(frame, text=tr("The PC shows a Windows notification when a value stays at or above its limit. This also applies to a connected Android / Raspberry Pi device."),
                 font=font_label, text_color=TEXT_DIM, wraplength=900,
                 justify="left").pack(anchor="w", padx=20, pady=(0, 10))

    self.alerts_enabled_switch = ctk.CTkSwitch(
        frame, text=tr("Send notifications"), font=font_bold, text_color=TEXT,
        progress_color=ACCENT)
    self.alerts_enabled_switch.pack(anchor="w", padx=20, pady=(0, 6))
    if self.alert_settings["alerts_enabled"]:
        self.alerts_enabled_switch.select()
    grid = ctk.CTkFrame(frame, fg_color="transparent")
    grid.pack(fill="x", padx=14, pady=(0, 6))
    for column in range(4):
        grid.grid_columnconfigure(column, weight=1, uniform="setting")

    self.settings_entries = {}

    def field(row, column, key, label, hint):
        cell = ctk.CTkFrame(grid, fg_color=CARD_SOFT, corner_radius=12)
        cell.grid(row=row, column=column, padx=6, pady=6, sticky="nsew")
        ctk.CTkLabel(cell, text=tr(label), font=font_label,
                     text_color=TEXT_DIM).pack(anchor="w", padx=16, pady=(12, 2))
        entry = ctk.CTkEntry(cell, width=120, height=34, corner_radius=10, fg_color=CARD,
                             border_color=TEXT_DIM, border_width=1, text_color=TEXT,
                             font=font_label)
        value = self.alert_settings[key]
        entry.insert(0, f"{value:g}" if isinstance(value, float) else str(value))
        entry.pack(anchor="w", padx=16, pady=(0, 4))
        ctk.CTkLabel(cell, text=tr(hint), font=ctk.CTkFont(family="Segoe UI", size=11),
                     text_color=TEXT_DIM).pack(anchor="w", padx=16, pady=(0, 10))
        self.settings_entries[key] = entry

    field(0, 0, "cpu", "CPU limit (%)", "Alert at or above")
    field(0, 1, "memory", "Memory limit (%)", "Alert at or above")
    field(0, 2, "gpu", "GPU limit (%)", "Ignored if GPU reads 0")
    field(0, 3, "gpu_memory", "GPU memory limit (%)", "Ignored if it reads 0")
    field(1, 0, "duration_seconds", "Alert after (s)", "Time above the limit")
    field(1, 1, "cooldown_minutes", "Repeat after (min)", "Gap between alerts")
    field(1, 2, "interval_seconds", "Update interval (s)", "How often to measure")
    field(1, 3, "history_days", "Keep history (days)", "Older records are deleted")

    actions = ctk.CTkFrame(frame, fg_color="transparent")
    actions.pack(anchor="w", padx=20, pady=(10, 4))
    ctk.CTkButton(actions, text=tr("Save settings"), command=self.save_settings_from_ui,
                  fg_color=ACCENT, hover_color="#5d84d4", text_color="#0f1117",
                  corner_radius=10, height=36, font=font_bold).pack(side="left", padx=(0, 8))
    ctk.CTkButton(actions, text=tr("Send test notification"), command=self.send_test_notification,
                  fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
                  corner_radius=10, height=36, font=font_label).pack(side="left")
    self.settings_status_label = ctk.CTkLabel(frame, text="", font=font_label,
                                              text_color=TEXT_DIM)
    self.settings_status_label.pack(anchor="w", padx=20, pady=(4, 4))

    ctk.CTkLabel(frame, text=tr("RAM cleanup"), font=font_title,
                 text_color=TEXT).pack(anchor="w", padx=20, pady=(10, 2))
    self.purge_standby_switch = ctk.CTkSwitch(
        frame, text=tr("Memory cleanup also purges the standby list (frees the most RAM; apps may reload files from disk once)"),
        font=font_label, text_color=TEXT,
        progress_color=ACCENT)
    self.purge_standby_switch.pack(anchor="w", padx=20, pady=(0, 8))
    if self.alert_settings["purge_standby"]:
        self.purge_standby_switch.select()

    self.settings_clean_button = ctk.CTkButton(frame, text=tr("🧹  Clean RAM now"), width=150,
                                               command=self.clean_memory_now)
    self.settings_clean_button.pack(anchor="w", padx=20, pady=(0, 16))



def create_gui(self):
    self.root.configure(fg_color=BG)

    # 공통 폰트
    font_title = ctk.CTkFont(family="Segoe UI", size=18, weight="bold")
    font_label = ctk.CTkFont(family="Segoe UI", size=13)
    font_bold  = ctk.CTkFont(family="Segoe UI", size=14, weight="bold")
    font_mono  = ctk.CTkFont(family="Consolas", size=12)

    # ==================== 메인 컨테이너 ====================
    main_frame = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
    main_frame.pack(fill="both", expand=True, padx=16, pady=16)

    # 탭 뷰 (둥근 모서리 + 다크)
    top_bar = ctk.CTkFrame(main_frame, fg_color="transparent")
    top_bar.pack(fill="x", pady=(0, 10))
    ctk.CTkLabel(top_bar, text=tr("System Resource Monitor"),
                 font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
                 text_color=TEXT).pack(side="left", padx=4)
    self.theme_toggle_button = ctk.CTkButton(
        top_bar, text=tr("Light"), width=76, height=30, corner_radius=8,
        fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
        font=ctk.CTkFont(family="Segoe UI", size=11), command=self.toggle_theme)
    self.theme_toggle_button.pack(side="right", padx=4)
    self.fullscreen_toggle_button = ctk.CTkButton(
        top_bar, text=tr("Fullscreen"), width=92, height=30, corner_radius=8,
        fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
        font=ctk.CTkFont(family="Segoe UI", size=11), command=self.toggle_fullscreen)
    self.fullscreen_toggle_button.pack(side="right", padx=4)

    self.tab_control = ctk.CTkTabview(
        main_frame,
        fg_color=CARD,
        segmented_button_fg_color=CARD_SOFT,
        segmented_button_selected_color=ACCENT,
        segmented_button_selected_hover_color=ACCENT,
        text_color=TEXT,
        corner_radius=16,
    )
    self.tab_control.pack(expand=True, fill="both")

    self.tab_keys = ["📊 Resource Monitor", "🔧 Top Processes", "📈 History", "⚙ Settings"]
    monitor_tab = self.tab_control.add(tr(self.tab_keys[0]))
    processes_tab = self.tab_control.add(tr(self.tab_keys[1]))
    history_tab = self.tab_control.add(tr(self.tab_keys[2]))
    settings_tab = self.tab_control.add(tr(self.tab_keys[3]))
    build_history_tab(self, history_tab, font_title, font_label, font_bold)
    build_settings_tab(self, settings_tab, font_title, font_label, font_bold)

    # ======================================================
    #  MONITORING TAB
    # ======================================================

    # ---- Control Panel 카드 ----
    # Current resource readings as large text percentages
    metrics_frame = ctk.CTkFrame(monitor_tab, fg_color=CARD, corner_radius=16)
    metrics_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
    ctk.CTkLabel(metrics_frame, text=tr("Current Resource Usage"), font=font_title,
                 text_color=TEXT).pack(anchor="w", padx=20, pady=(16, 10))

    values_grid = ctk.CTkFrame(metrics_frame, fg_color="transparent")
    values_grid.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    values_grid.grid_columnconfigure((0, 1), weight=1, uniform="metric")
    values_grid.grid_rowconfigure((0, 1), weight=1, uniform="metric")

    self.metric_labels = {}
    for key, title, row, column, color in (
        ("cpu", "CPU", 0, 0, ACCENT),
        ("memory", "Memory", 0, 1, GOOD),
        ("gpu", "GPU", 1, 0, "#ff9e64"),
        ("gpu_memory", "GPU Memory", 1, 1, "#bb9af7"),
    ):
        card = ctk.CTkFrame(values_grid, fg_color=CARD_SOFT, corner_radius=14)
        card.grid(row=row, column=column, padx=8, pady=8, sticky="nsew")
        ctk.CTkLabel(card, text=tr(title), font=font_bold,
                     text_color=TEXT_DIM).pack(pady=(18, 2))
        value = ctk.CTkLabel(card, text="--%", font=ctk.CTkFont(
            family="Segoe UI", size=36, weight="bold"), text_color=color)
        value.pack(expand=True, pady=(0, 18))
        self.metric_labels[key] = value

    def update_metric_values(cpu, memory, gpu, gpu_memory):
        values = {"cpu": cpu, "memory": memory, "gpu": gpu, "gpu_memory": gpu_memory}
        for key, value in values.items():
            self.metric_labels[key].configure(text=f"{value:.1f}%")
    self.update_metric_values = update_metric_values

    # ---- AI insights: a plain-language summary of the last minute ----
    insight_frame = ctk.CTkFrame(monitor_tab, fg_color=CARD, corner_radius=16)
    # Packed at the bottom (before the metric cards) so it never gets pushed off-screen.
    insight_frame.pack(side="bottom", fill="x", padx=4, pady=(0, 10), before=metrics_frame)
    insight_header = ctk.CTkFrame(insight_frame, fg_color="transparent")
    insight_header.pack(fill="x", padx=20, pady=(14, 6))
    ctk.CTkLabel(insight_header, text=tr("AI Insights"), font=font_title,
                 text_color=TEXT).pack(side="left")
    self.insight_mode_label = ctk.CTkLabel(
        insight_header, text="", font=font_label, text_color=TEXT_DIM)
    self.insight_mode_label.pack(side="left", padx=12)
    ctk.CTkButton(insight_header, text=tr("API key"), width=80, height=28, corner_radius=8,
                  fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
                  command=self.configure_ai_key).pack(side="right", padx=(6, 0))
    self.insight_auto_switch = ctk.CTkSwitch(
        insight_header, text=tr("Auto (60s)"), font=font_label, text_color=TEXT,
        progress_color=ACCENT, command=self.toggle_auto_insights)
    self.insight_auto_switch.pack(side="right", padx=6)
    self.insight_button = ctk.CTkButton(
        insight_header, text=tr("Analyze now"), width=110, height=28, corner_radius=8,
        command=self.run_ai_insights)
    self.insight_button.pack(side="right", padx=6)
    self.insight_text = ctk.CTkTextbox(
        insight_frame, height=90, corner_radius=12, fg_color=CARD_SOFT,
        text_color=TEXT, font=ctk.CTkFont(family="Malgun Gothic", size=13), wrap="word")
    self.insight_text.pack(fill="x", padx=16, pady=(0, 14))
    self.insight_text.insert("1.0", tr("Start Monitoring, then press Analyze now to get a summary of how the CPU, memory, and GPU are being used."))
    self.insight_text.configure(state="disabled")
    self.refresh_insight_mode()


    control_frame = ctk.CTkFrame(monitor_tab, fg_color=CARD, corner_radius=16)
    # Bottom-most and allocated first, so Start/Stop stay visible at any window height.
    control_frame.pack(side="bottom", fill="x", pady=(0, 4), padx=4, before=insight_frame)

    # Header row: title + status on the left, Start / Stop / Export on the right.
    self.control_header = ctk.CTkFrame(control_frame, fg_color="transparent")
    self.control_header.pack(fill="x", padx=20, pady=(14, 10))
    ctk.CTkLabel(self.control_header, text=tr("Control Panel"),
                 font=font_title, text_color=TEXT).pack(side="left")
    self.status_label = ctk.CTkLabel(
        self.control_header, text=tr("● Monitoring Stopped"),
        font=font_bold, text_color=self.bad_color)
    self.status_label.pack(side="left", padx=16)
    button_frame = ctk.CTkFrame(self.control_header, fg_color="transparent")
    button_frame.pack(side="right")

    # Shown only after an alert has fired.
    self.last_alert_label = ctk.CTkLabel(
        control_frame, text="", font=font_label, text_color=TEXT_DIM, anchor="w")

    # Remote device controls: the PC shows a 5-digit code that the agent enters.
    remote_frame = ctk.CTkFrame(control_frame, fg_color=CARD_SOFT, corner_radius=12)
    remote_frame.pack(fill="x", padx=20, pady=(0, 16))
    remote_header = ctk.CTkFrame(remote_frame, fg_color="transparent")
    remote_header.pack(fill="x", padx=12, pady=(8, 2))
    ctk.CTkLabel(remote_header, text=tr("Remote devices (Wi-Fi / LAN)"), font=font_bold,
                 text_color=TEXT).pack(side="left")
    self.remote_status_label = ctk.CTkLabel(
        remote_header, text=tr("Not connected"), font=font_label, text_color=TEXT_DIM)
    self.remote_status_label.pack(side="right")

    remote_actions = ctk.CTkFrame(remote_frame, fg_color="transparent")
    remote_actions.pack(fill="x", padx=8, pady=(2, 8))
    self.remote_connect_button = ctk.CTkButton(
        remote_actions, text=tr("Connect device"), command=self.open_pairing_dialog, width=145)
    self.remote_connect_button.pack(side="left", padx=4)
    self.remote_disconnect_button = ctk.CTkButton(
        remote_actions, text=tr("Disconnect"), command=self.disconnect_remote_device,
        width=130, state="disabled")
    self.remote_disconnect_button.pack(side="left", padx=4)

    # ---- 제어 버튼 (header row) ----

    def wrap_status(start):
        def _cmd():
            if start:
                self.start_monitoring()
                self.status_label.configure(text=tr("● Monitoring Active"), text_color=self.good_color)
                self.start_button.configure(state="disabled")
                self.stop_button.configure(state="normal")
            else:
                self.stop_monitoring()
                self.status_label.configure(text=tr("● Monitoring Stopped"), text_color=self.bad_color)
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
        return _cmd

    self.start_button = ctk.CTkButton(
        button_frame, text=tr("▶  Start Monitoring"), command=wrap_status(True),
        fg_color=ACCENT, hover_color="#5d84d4", text_color="#0f1117",
        corner_radius=10, height=38, font=font_bold)
    self.start_button.pack(side="left", padx=(0, 6))

    self.stop_button = ctk.CTkButton(
        button_frame, text=tr("⏹  Stop Monitoring"), command=wrap_status(False),
        state="disabled", fg_color=CARD_SOFT, hover_color="#2c2f3f",
        text_color=TEXT, corner_radius=10, height=38, font=font_bold)
    self.stop_button.pack(side="left", padx=6)

    export_button = ctk.CTkButton(
        button_frame, text=tr("💾  Export Data"), command=self.export_data,
        fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
        corner_radius=10, height=38, font=font_bold)
    export_button.pack(side="left", padx=(6, 0))

    # ---- 그래프 카드 ----
    process_card = ctk.CTkFrame(processes_tab, fg_color=CARD, corner_radius=16)
    process_card.pack(fill="both", expand=True, padx=4, pady=4)

    header_layout_frame = ctk.CTkFrame(process_card, fg_color="transparent")
    header_layout_frame.pack(fill="x", padx=20, pady=(16, 8))

    self.process_title_label = ctk.CTkLabel(
        header_layout_frame, text=tr("Top 20 Processes by CPU Usage"),
        font=font_title, text_color=TEXT)
    self.process_title_label.pack(side="left")

    export_proc_button = ctk.CTkButton(
        header_layout_frame, text=tr("💾  Export Processes"),
        command=self.export_top_processes,
        fg_color=ACCENT, hover_color="#5d84d4", text_color="#0f1117",
        corner_radius=10, height=34, font=font_bold)
    export_proc_button.pack(side="right")

    # 테이블 헤더 라벨
    th_frame = ctk.CTkFrame(process_card, fg_color=CARD_SOFT, corner_radius=10, height=36)
    th_frame.pack(fill="x", padx=16, pady=(0, 6))
    th_frame.pack_propagate(False)

    ctk.CTkLabel(th_frame, text="PID", font=font_bold, text_color=ACCENT, width=80, anchor="w").pack(side="left", padx=(16, 0))
    ctk.CTkLabel(th_frame, text=tr("Process Name"), font=font_bold, text_color=ACCENT, anchor="w").pack(side="left", expand=True, fill="x", padx=10)
    ctk.CTkLabel(th_frame, text=tr("CPU Usage"), font=font_bold, text_color=ACCENT, width=120, anchor="e").pack(side="right", padx=10)
    ctk.CTkLabel(th_frame, text=tr("Memory"), font=font_bold, text_color=ACCENT, width=120, anchor="e").pack(side="right", padx=(0, 10))

    # 개별 프로세스 카드들이 담길 스크롤 가능한 영역 (여기가 진짜 도시락통 그리드야!)
    self.process_scroll_frame = ctk.CTkScrollableFrame(
        process_card, fg_color="#16171f", corner_radius=12,
        scrollbar_button_color=CARD_SOFT, scrollbar_button_hover_color=ACCENT)
    self.process_scroll_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    self.update_process_info()
