import customtkinter as ctk
from tkinter import messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from utils.utils import gather_system_info
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

    monitor_tab = self.tab_control.add("📊 Resource Monitor")
    processes_tab = self.tab_control.add("🔧 Top Processes")

    # ======================================================
    #  MONITORING TAB
    # ======================================================

    # ---- Control Panel 카드 ----
    control_frame = ctk.CTkFrame(monitor_tab, fg_color=CARD, corner_radius=16)
    control_frame.pack(fill="x", pady=(0, 14), padx=4)

    ctk.CTkLabel(control_frame, text="Control Panel",
                 font=font_title, text_color=TEXT).pack(
        anchor="w", padx=20, pady=(16, 4))

    # 상태 표시
    self.status_label = ctk.CTkLabel(
        control_frame, text="● Monitoring Stopped",
        font=font_bold, text_color=BAD)
    self.status_label.pack(anchor="w", padx=20, pady=(0, 10))

    # ---- 임계값 "도시락통" 그리드 (2x2 카드) ----
    threshold_grid = ctk.CTkFrame(control_frame, fg_color="transparent")
    threshold_grid.pack(fill="x", padx=16, pady=(0, 12))
    for c in range(2):
        threshold_grid.grid_columnconfigure(c, weight=1, uniform="cell")

    def make_field(parent, label, initial):
        cell = ctk.CTkFrame(parent, fg_color=CARD_SOFT, corner_radius=12)
        ctk.CTkLabel(cell, text=label, font=font_label,
                     text_color=TEXT_DIM).pack(anchor="w", padx=16, pady=(12, 2))
        entry = ctk.CTkEntry(
            cell, width=120, height=34, corner_radius=10,
            fg_color=CARD, border_color=TEXT_DIM, border_width=1,
            text_color=TEXT, font=font_label)
        entry.insert(0, str(initial))
        entry.pack(anchor="w", padx=16, pady=(0, 14))
        return cell, entry

    cpu_cell, cpu_entry = make_field(threshold_grid, "CPU Threshold (%)", self.CPU_THRESHOLD)
    mem_cell, memory_entry = make_field(threshold_grid, "Memory Threshold (%)", self.MEMORY_THRESHOLD)
    gpu_cell, gpu_entry = make_field(threshold_grid, "GPU Threshold (%)", self.GPU_THRESHOLD)
    int_cell, interval_entry = make_field(threshold_grid, "Update Interval (s)", self.CPU_MON_INTERVAL)

    cpu_cell.grid(row=0, column=0, padx=6, pady=6, sticky="nsew")
    mem_cell.grid(row=0, column=1, padx=6, pady=6, sticky="nsew")
    gpu_cell.grid(row=1, column=0, padx=6, pady=6, sticky="nsew")
    int_cell.grid(row=1, column=1, padx=6, pady=6, sticky="nsew")

    def save_cpu_threshold(event=None):
        try:
            self.CPU_THRESHOLD = float(cpu_entry.get())
        except ValueError:
            cpu_entry.delete(0, "end")
            cpu_entry.insert(0, str(self.CPU_THRESHOLD))

    def save_memory_threshold(event=None):
        try:
            self.MEMORY_THRESHOLD = float(memory_entry.get())
        except ValueError:
            memory_entry.delete(0, "end")
            memory_entry.insert(0, str(self.MEMORY_THRESHOLD))

    def save_gpu_threshold(event=None):
        try:
            self.GPU_THRESHOLD = float(gpu_entry.get())
        except ValueError:
            gpu_entry.delete(0, "end")
            gpu_entry.insert(0, str(self.GPU_THRESHOLD))

    def save_interval(event=None):
        try:
            self.CPU_MON_INTERVAL = float(interval_entry.get())
        except ValueError:
            interval_entry.delete(0, "end")
            interval_entry.insert(0, str(self.CPU_MON_INTERVAL))

    cpu_entry.bind("<Return>", save_cpu_threshold)
    memory_entry.bind("<Return>", save_memory_threshold)
    gpu_entry.bind("<Return>", save_gpu_threshold)
    interval_entry.bind("<Return>", save_interval)

    # ---- 제어 버튼 ----
    button_frame = ctk.CTkFrame(control_frame, fg_color="transparent")
    button_frame.pack(anchor="w", padx=20, pady=(0, 16))

    def wrap_status(start):
        def _cmd():
            if start:
                self.start_monitoring()
                self.status_label.configure(text="● Monitoring Active", text_color=GOOD)
                self.start_button.configure(state="disabled")
                self.stop_button.configure(state="normal")
            else:
                self.stop_monitoring()
                self.status_label.configure(text="● Monitoring Stopped", text_color=BAD)
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
        return _cmd

    self.start_button = ctk.CTkButton(
        button_frame, text="▶  Start Monitoring", command=wrap_status(True),
        fg_color=ACCENT, hover_color="#5d84d4", text_color="#0f1117",
        corner_radius=10, height=38, font=font_bold)
    self.start_button.pack(side="left", padx=(0, 8))

    self.stop_button = ctk.CTkButton(
        button_frame, text="⏹  Stop Monitoring", command=wrap_status(False),
        state="disabled", fg_color=CARD_SOFT, hover_color="#2c2f3f",
        text_color=TEXT, corner_radius=10, height=38, font=font_bold)
    self.stop_button.pack(side="left", padx=8)

    export_button = ctk.CTkButton(
        button_frame, text="💾  Export Data", command=self.export_data,
        fg_color=CARD_SOFT, hover_color="#2c2f3f", text_color=TEXT,
        corner_radius=10, height=38, font=font_bold)
    export_button.pack(side="left", padx=8)

    # ---- 그래프 카드 ----
    graph_frame = ctk.CTkFrame(monitor_tab, fg_color=CARD, corner_radius=16)
    graph_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    ctk.CTkLabel(graph_frame, text="Real-time Resource Usage",
                 font=font_title, text_color=TEXT).pack(
        anchor="w", padx=20, pady=(16, 4))

    plt.style.use("dark_background")
    self.fig, ((self.ax1, self.ax2), (self.ax3, self.ax4)) = plt.subplots(2, 2, figsize=(12, 8))
    self.fig.patch.set_facecolor(CARD)

    for ax in (self.ax1, self.ax2, self.ax3, self.ax4):
        ax.set_facecolor("#16171f")
        ax.grid(True, alpha=0.15, color=TEXT_DIM)
        ax.tick_params(colors=TEXT_DIM, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(TEXT_DIM)
            spine.set_alpha(0.3)

    self.ax1.set_title("CPU Usage", color=TEXT, fontweight="bold")
    self.ax1.set_ylabel("Percentage (%)", color=TEXT_DIM)
    self.ax2.set_title("Memory Usage", color=TEXT, fontweight="bold")
    self.ax2.set_ylabel("Percentage (%)", color=TEXT_DIM)
    self.ax3.set_title("GPU Usage", color=TEXT, fontweight="bold")
    self.ax3.set_ylabel("Percentage (%)", color=TEXT_DIM)
    self.ax3.set_xlabel("Time", color=TEXT_DIM)
    self.ax4.set_title("GPU Memory", color=TEXT, fontweight="bold")
    self.ax4.set_ylabel("Percentage (%)", color=TEXT_DIM)
    self.ax4.set_xlabel("Time", color=TEXT_DIM)

    self.fig.tight_layout(pad=2.0)

    canvas_holder = ctk.CTkFrame(graph_frame, fg_color=CARD, corner_radius=12)
    canvas_holder.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    self.canvas = FigureCanvasTkAgg(self.fig, master=canvas_holder)
    self.canvas.get_tk_widget().configure(bg=CARD, highlightthickness=0)
    self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ======================================================
    #  PROCESSES TAB (카드 그리드 스타일로 변경)
    # ======================================================
    process_card = ctk.CTkFrame(processes_tab, fg_color=CARD, corner_radius=16)
    process_card.pack(fill="both", expand=True, padx=4, pady=4)

    header_layout_frame = ctk.CTkFrame(process_card, fg_color="transparent")
    header_layout_frame.pack(fill="x", padx=20, pady=(16, 8))

    ctk.CTkLabel(header_layout_frame, text="Top 20 Processes by CPU Usage",
                 font=font_title, text_color=TEXT).pack(side="left")

    export_proc_button = ctk.CTkButton(
        header_layout_frame, text="💾  Export Processes",
        command=self.export_top_processes,
        fg_color=ACCENT, hover_color="#5d84d4", text_color="#0f1117",
        corner_radius=10, height=34, font=font_bold)
    export_proc_button.pack(side="right")

    # 테이블 헤더 라벨
    th_frame = ctk.CTkFrame(process_card, fg_color=CARD_SOFT, corner_radius=10, height=36)
    th_frame.pack(fill="x", padx=16, pady=(0, 6))
    th_frame.pack_propagate(False)

    ctk.CTkLabel(th_frame, text="PID", font=font_bold, text_color=ACCENT, width=80, anchor="w").pack(side="left", padx=(16, 0))
    ctk.CTkLabel(th_frame, text="Process Name", font=font_bold, text_color=ACCENT, anchor="w").pack(side="left", expand=True, fill="x", padx=10)
    ctk.CTkLabel(th_frame, text="CPU Usage", font=font_bold, text_color=ACCENT, width=120, anchor="e").pack(side="right", padx=10)
    ctk.CTkLabel(th_frame, text="Memory", font=font_bold, text_color=ACCENT, width=120, anchor="e").pack(side="right", padx=(0, 10))

    # 개별 프로세스 카드들이 담길 스크롤 가능한 영역 (여기가 진짜 도시락통 그리드야!)
    self.process_scroll_frame = ctk.CTkScrollableFrame(
        process_card, fg_color="#16171f", corner_radius=12,
        scrollbar_button_color=CARD_SOFT, scrollbar_button_hover_color=ACCENT)
    self.process_scroll_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    self.update_process_info()