import tkinter as tk
import customtkinter as ctk
from tkinter import ttk
from collections import deque
import threading
from tkinter import messagebox
from utils.utils import export_data
from .monitor import monitor_resources, update_graph
from .gui import create_gui
import psutil
import queue
import time
from concurrent.futures import ThreadPoolExecutor

class ResourceMonitor:
    def __init__(self, current_version):
        self.CURRENT_VERSION = current_version
        self.CPU_THRESHOLD = 85
        self.MEMORY_THRESHOLD = 90
        self.GPU_THRESHOLD = 99.5
        self.HISTORY_LENGTH = 60
        self.CPU_MON_INTERVAL = 1

        self.cpu_history = deque(maxlen=self.HISTORY_LENGTH)
        self.memory_history = deque(maxlen=self.HISTORY_LENGTH)
        self.gpu_history = deque(maxlen=self.HISTORY_LENGTH)
        self.gpu_memory_history = deque(maxlen=self.HISTORY_LENGTH)
        self.time_history = deque(maxlen=self.HISTORY_LENGTH)

        self.all_cpu_history = []
        self.all_memory_history = []
        self.all_gpu_history = []
        self.all_gpu_memory_history = []
        self.all_time_history = []

        self.monitoring = False
        self.process_queue = queue.Queue()
        self.process_monitoring_thread = None

        self.root = ctk.CTk()
        self.root.title("System Resource Monitor v2.0")
        self.root.minsize(900, 800)
        self.root.maxsize(1200, 900)
        
        # Modern styling
        self.setup_styles()
        
        # Center the window
        window_width = 1000
        window_height = 850
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 3
        self.root.geometry(f'{window_width}x{window_height}+{x}+{y}')

        # Create GUI
        create_gui(self)

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

    def update_process_info(self):
        try:
            # 1. 큐에서 정렬된 프로세스 데이터(리스트) 가져오기
            all_sorted_processes = self.process_queue.get_nowait()
            
            # 2. 기존에 그려져 있던 카드들 싹 지우기 (초기화)
            for widget in self.process_scroll_frame.winfo_children():
                widget.destroy()

            font_row = ctk.CTkFont(family="Segoe UI", size=13)
            font_mono = ctk.CTkFont(family="Consolas", size=12, weight="bold")

            # 3. 프로세스 개수만큼 예쁜 둥근 카드(도시락통) 한 줄씩 생성해서 꽂기
            for idx, proc in enumerate(all_sorted_processes):
                # 카드 배경 색상 (번갈아가며 살짝 다르게 주면 가독성이 좋아져!)
                row_bg = "#1a1b26" if idx % 2 == 0 else "#20222e"
                
                row_card = ctk.CTkFrame(self.process_scroll_frame, fg_color=row_bg, corner_radius=8, height=40)
                row_card.pack(fill="x", pady=3, padx=2)
                row_card.pack_propagate(False)

                # PID 정보
                pid_lbl = ctk.CTkLabel(row_card, text=str(proc['pid']), font=font_mono, text_color="#c0caf5", width=80, anchor="w")
                pid_lbl.pack(side="left", padx=(12, 0))

                # 프로세스 이름 정보
                name_lbl = ctk.CTkLabel(row_card, text=str(proc['name']), font=font_row, text_color="#c0caf5", anchor="w")
                name_lbl.pack(side="left", expand=True, fill="x", padx=10)

                # 메모리 사용량 정보
                mem_val = f"{proc['memory_percent']:.2f}%"
                mem_lbl = ctk.CTkLabel(row_card, text=mem_val, font=font_row, text_color="#9ece6a", width=120, anchor="e")
                mem_lbl.pack(side="right", padx=10)

                # CPU 사용량 정보
                cpu_val = f"{proc['cpu_percent_normalized']:.2f}%"
                cpu_lbl = ctk.CTkLabel(row_card, text=cpu_val, font=font_row, text_color="#7aa2f7", width=120, anchor="e")
                cpu_lbl.pack(side="right", padx=(0, 10))

        except queue.Empty:
            pass
        except Exception as e:
            # 혹시 모를 에러 방어
            pass

        self.root.after(1000, self.update_process_info)

    def export_top_processes(self):
        """Export the current list of processes to a file."""
        try:
            process_text = self.process_list.get(1.0, tk.END).strip()

            if not process_text:
                messagebox.showwarning("Export Failed", "No processes to export.")
                return

            with open("top_processes.txt", "w") as file:
                file.write(process_text)
                messagebox.showinfo("Export Successful", 
                                  "Processes exported to 'top_processes.txt'")

        except Exception as e:
            messagebox.showerror("Export Failed", 
                               f"An error occurred while exporting: {e}")

    def start_monitoring(self):
        if not self.monitoring:
            self.monitoring = True

            # Start monitoring threads
            self.monitor_thread = threading.Thread(target=monitor_resources, 
                                                 args=(self,), daemon=True)
            self.graph_thread = threading.Thread(target=update_graph, 
                                               args=(self,), daemon=True)
            self.monitor_thread.start()
            self.graph_thread.start()

            if hasattr(self, 'monitor_top_processes'):
                self.process_monitoring_thread = threading.Thread(
                    target=self.monitor_top_processes, daemon=True)
                self.process_monitoring_thread.start()

            # Update GUI state
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            self.status_label.configure(text="🟢 Monitoring Active", 
                                   text_color="#107c10")

    def stop_monitoring(self):
        self.monitoring = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="🔴 Monitoring Stopped", 
                               text_color="#d13438")

    def monitor_top_processes(self):
        """Monitor all processes and order them by CPU usage."""
        def monitor_chunk(process_chunk):
            processes = []
            for proc in process_chunk:
                try:
                    cpu_percent = proc.info['cpu_percent'] / psutil.cpu_count()
                    proc.info['cpu_percent_normalized'] = cpu_percent
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            return processes

        while self.monitoring:
            try:
                all_processes = list(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']))

                chunk_size = max(1, len(all_processes) // 5)
                process_chunks = [all_processes[i:i + chunk_size]
                                  for i in range(0, len(all_processes), chunk_size)]

                with ThreadPoolExecutor(max_workers=5) as executor:
                    results = executor.map(monitor_chunk, process_chunks)

                all_sorted_processes = sorted(
                    [proc for chunk in results for proc in chunk],
                    key=lambda p: p['cpu_percent_normalized'],
                    reverse=True
                )[:20]

                self.process_queue.put(all_sorted_processes)

            except Exception as e:
                messagebox.showerror("Error",
                                   f"Error monitoring processes: {e}")

            time.sleep(2)

    def export_data(self):
        export_data(self)

    def cleanup(self):
        self.monitoring = False
        self.root.quit()